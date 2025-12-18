<#
.SYNOPSIS
    Mirrors Cloud MDR notification block settings from a template tenant to all other tenants.

.DESCRIPTION
    This script allows partners to programmatically mirror Cloud MDR notification blocklist settings
    across all their tenants. It uses one tenant as a "template" and ensures all other tenants
    match that exact block state for Cloud MDR notification types.

    Cloud MDR Notification Types covered:
    - CloudResponseNotification (Google Workspace security alerts)
    - CiscoDuoNotification (Cisco Duo security alerts)
    - MS365DefenseNotification (Microsoft 365 security alerts)
    - MS365DefenseNewPermsNotification (Microsoft 365 new permissions alerts)
    - MdeNewPermsNotification (Microsoft Defender for Endpoint new permissions alerts)

.PARAMETER DryRun
    When specified, the script will log what changes it would make without actually making them.

.EXAMPLE
    .\Mirror-CloudMdrNotifications.ps1
    Runs the script interactively, prompting for all required inputs.

.EXAMPLE
    .\Mirror-CloudMdrNotifications.ps1 -DryRun
    Runs the script in dry-run mode, showing what changes would be made without executing them.

.NOTES
    Author: Blackpoint Cyber
    Version: 1.1.0
    Requires: PowerShell 5.1 or later
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Cloud MDR notification types to synchronize
# Updated list based on available notification types
$CloudMdrNotificationTypes = @(
    "CloudResponseNotification",         # Google Workspace security alerts
    "CiscoDuoNotification",              # Cisco Duo security alerts
    "MS365DefenseNotification",          # Microsoft 365 security alerts
    "MS365DefenseNewPermsNotification",  # Microsoft 365 new permissions alerts
    "MdeNewPermsNotification"            # Microsoft Defender for Endpoint new permissions alerts
)

# API pagination settings
$PageSize = 50

# Rate limiting - delay between API calls (milliseconds)
# Conservative default: 500ms between requests
$ApiDelayMs = 500

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

function Write-Status {
    param(
        [string]$Message,
        [ValidateSet("Info", "Success", "Warning", "Error", "Progress", "Debug")]
        [string]$Type = "Info"
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    switch ($Type) {
        "Info"     { Write-Host "[$timestamp] [INFO] $Message" -ForegroundColor Cyan }
        "Success"  { Write-Host "[$timestamp] [SUCCESS] $Message" -ForegroundColor Green }
        "Warning"  { Write-Host "[$timestamp] [WARNING] $Message" -ForegroundColor Yellow }
        "Error"    { Write-Host "[$timestamp] [ERROR] $Message" -ForegroundColor Red }
        "Progress" { Write-Host "[$timestamp] [PROGRESS] $Message" -ForegroundColor Magenta }
        "Debug"    { Write-Host "[$timestamp] [DEBUG] $Message" -ForegroundColor DarkGray }
    }
}

function Write-DryRunAction {
    param([string]$Message)
    Write-Host "  [DRY-RUN] $Message" -ForegroundColor DarkYellow
}

function Get-SecureInput {
    param(
        [string]$Prompt,
        [switch]$AsSecureString
    )
    
    if ($AsSecureString) {
        $secureString = Read-Host -Prompt $Prompt -AsSecureString
        # Convert SecureString back to plain text for API use
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureString)
        try {
            return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        }
        finally {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
    else {
        return Read-Host -Prompt $Prompt
    }
}

function Invoke-CompassOneApi {
    param(
        [string]$BaseUrl,
        [string]$Endpoint,
        [string]$Method = "GET",
        [string]$ApiKey,
        [hashtable]$Body = $null,
        [hashtable]$QueryParams = $null
    )
    
    # Build URL with query parameters
    $url = "$BaseUrl$Endpoint"
    if ($QueryParams -and $QueryParams.Count -gt 0) {
        $queryString = ($QueryParams.GetEnumerator() | ForEach-Object { 
            "$([uri]::EscapeDataString($_.Key))=$([uri]::EscapeDataString($_.Value))" 
        }) -join "&"
        $url = "$url`?$queryString"
    }
    
    $headers = @{
        "Authorization" = "Bearer $ApiKey"
        "Content-Type"  = "application/json"
    }
    
    $params = @{
        Uri         = $url
        Method      = $Method
        Headers     = $headers
        ErrorAction = "Stop"
    }
    
    # For POST, PUT, PATCH, DELETE - add body if provided
    if ($Body -and $Method -in @("POST", "PUT", "PATCH", "DELETE")) {
        $jsonBody = ($Body | ConvertTo-Json -Depth 10)
        $params.Body = $jsonBody
        Write-Status "API Request: $Method $url" -Type Debug
        Write-Status "Request Body: $jsonBody" -Type Debug
    }
    else {
        Write-Status "API Request: $Method $url" -Type Debug
    }
    
    try {
        # Add delay to respect rate limits
        Start-Sleep -Milliseconds $ApiDelayMs
        
        $response = Invoke-WebRequest @params -UseBasicParsing
        
        # Check rate limit headers
        $remaining = $response.Headers["ratelimit-remaining"]
        if ($remaining -and [int]$remaining -lt 100) {
            Write-Status "Rate limit warning: Only $remaining requests remaining" -Type Warning
        }
        
        Write-Status "API Response Status: $($response.StatusCode)" -Type Debug
        
        if ($response.Content) {
            $parsedResponse = $response.Content | ConvertFrom-Json
            Write-Status "API Response Content: $($response.Content)" -Type Debug
            return $parsedResponse
        }
        return $null
    }
    catch {
        $statusCode = $null
        $errorMessage = $_.Exception.Message
        
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        
        Write-Status "API Error - Status: $statusCode, Message: $errorMessage" -Type Debug
        
        if ($statusCode -eq 429) {
            Write-Status "Rate limit exceeded. Please wait and try again." -Type Error
            throw "Rate limit exceeded (HTTP 429)"
        }
        elseif ($statusCode -eq 401) {
            throw "Authentication failed. Please check your API key."
        }
        elseif ($statusCode -eq 403) {
            throw "Access denied. Your API key may not have permission for this operation."
        }
        elseif ($statusCode -eq 404) {
            # For DELETE operations, 404 might be acceptable (already unblocked)
            if ($Method -eq "DELETE") {
                Write-Status "Resource not found (already unblocked): $Endpoint" -Type Debug
                return @{ success = $true; alreadyUnblocked = $true }
            }
            throw "Resource not found: $Endpoint"
        }
        else {
            throw "API error (HTTP $statusCode): $errorMessage"
        }
    }
}

function Get-AllTenants {
    param(
        [string]$BaseUrl,
        [string]$ApiKey
    )
    
    Write-Status "Fetching all tenants..." -Type Progress
    
    $allTenants = @()
    $currentPage = 1
    $totalPages = 1
    
    do {
        $queryParams = @{
            page      = $currentPage.ToString()
            pageSize  = $PageSize.ToString()
            sortBy    = "name"
            sortOrder = "ASC"
        }
        
        $response = Invoke-CompassOneApi -BaseUrl $BaseUrl -Endpoint "/v1/tenants" -ApiKey $ApiKey -QueryParams $queryParams
        
        if ($response.data) {
            $allTenants += $response.data
        }
        
        if ($response.meta) {
            $totalPages = $response.meta.totalPages
            Write-Status "  Fetched page $currentPage of $totalPages ($($allTenants.Count) tenants so far)" -Type Info
        }
        
        $currentPage++
        
    } while ($currentPage -le $totalPages)
    
    Write-Status "Fetched $($allTenants.Count) total tenants" -Type Success
    return $allTenants
}

function Get-TenantBlockStatus {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$TenantId,
        [string]$TenantName
    )
    
    $blockStatus = @{}
    
    foreach ($notificationType in $CloudMdrNotificationTypes) {
        $queryParams = @{
            tenantId  = $TenantId
            emailType = $notificationType
        }
        
        try {
            $response = Invoke-CompassOneApi -BaseUrl $BaseUrl -Endpoint "/v1/event-signal/blocklist/check" -ApiKey $ApiKey -QueryParams $queryParams
            
            # Handle different possible response formats
            if ($null -ne $response.blocked) {
                $blockStatus[$notificationType] = [bool]$response.blocked
            }
            elseif ($null -ne $response.isBlocked) {
                $blockStatus[$notificationType] = [bool]$response.isBlocked
            }
            elseif ($null -ne $response.status) {
                $blockStatus[$notificationType] = ($response.status -eq "blocked")
            }
            else {
                # If response exists but no known field, assume not blocked
                Write-Status "  Unknown response format for $notificationType - Response: $($response | ConvertTo-Json -Compress)" -Type Debug
                $blockStatus[$notificationType] = $false
            }
            
            Write-Status "  $notificationType : blocked = $($blockStatus[$notificationType])" -Type Debug
        }
        catch {
            Write-Status "  Failed to check $notificationType for tenant '$TenantName': $_" -Type Warning
            $blockStatus[$notificationType] = $null
        }
    }
    
    return $blockStatus
}

function Set-NotificationBlocked {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$TenantId,
        [string]$EmailType,
        [bool]$IsDryRun
    )
    
    if ($IsDryRun) {
        return $true
    }
    
    $body = @{
        tenantId  = $TenantId
        emailType = $EmailType
    }
    
    try {
        $response = Invoke-CompassOneApi -BaseUrl $BaseUrl -Endpoint "/v1/event-signal/blocklist" -Method "POST" -ApiKey $ApiKey -Body $body
        Write-Status "Block response: $($response | ConvertTo-Json -Compress)" -Type Debug
        return $true
    }
    catch {
        Write-Status "  Failed to block $EmailType`: $_" -Type Error
        return $false
    }
}

function Set-NotificationUnblocked {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$TenantId,
        [string]$EmailType,
        [bool]$IsDryRun
    )
    
    if ($IsDryRun) {
        return $true
    }
    
    $body = @{
        tenantId  = $TenantId
        emailType = $EmailType
    }
    
    try {
        $response = Invoke-CompassOneApi -BaseUrl $BaseUrl -Endpoint "/v1/event-signal/blocklist" -Method "DELETE" -ApiKey $ApiKey -Body $body
        Write-Status "Unblock response: $($response | ConvertTo-Json -Compress)" -Type Debug
        return $true
    }
    catch {
        # 404 is acceptable - notification might not have been blocked
        if ($_.Exception.Message -like "*404*" -or $_.Exception.Message -like "*not found*") {
            Write-Status "  Notification was already unblocked" -Type Debug
            return $true
        }
        Write-Status "  Failed to unblock $EmailType`: $_" -Type Error
        return $false
    }
}

# ============================================================================
# MAIN SCRIPT
# ============================================================================

function Main {
    # Display header
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  CompassOne Cloud MDR Notification Mirror Script" -ForegroundColor Cyan
    Write-Host "  Version 1.1.0" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    
    # Track if DryRun was set via parameter
    $isDryRun = $DryRun.IsPresent
    
    if ($isDryRun) {
        Write-Host "  *** DRY-RUN MODE ENABLED (via -DryRun flag) ***" -ForegroundColor Yellow
        Write-Host "  No changes will be made. Actions will be logged only." -ForegroundColor Yellow
        Write-Host ""
    }
    
    Write-Host "This script will mirror Cloud MDR notification block settings" -ForegroundColor White
    Write-Host "from a template tenant to all other tenants." -ForegroundColor White
    Write-Host ""
    Write-Host "Notification types that will be synchronized:" -ForegroundColor White
    foreach ($type in $CloudMdrNotificationTypes) {
        Write-Host "  - $type" -ForegroundColor Gray
    }
    Write-Host ""
    
    # -------------------------------------------------------------------------
    # STEP 1: Gather user inputs
    # -------------------------------------------------------------------------
    
    Write-Host "--- Configuration ---" -ForegroundColor Yellow
    Write-Host ""
    
    # Dry-run mode prompt (if not already specified via command line)
    if (-not $isDryRun) {
        $dryRunInput = Read-Host -Prompt "Run in dry-run mode? (yes = preview only, no = apply changes) [yes/no]"
        if ($dryRunInput -in @("yes", "y", "Y", "Yes", "YES")) {
            $isDryRun = $true
            Write-Host ""
            Write-Host "  *** DRY-RUN MODE ENABLED ***" -ForegroundColor Yellow
            Write-Host "  No changes will be made. Actions will be logged only." -ForegroundColor Yellow
        }
        else {
            Write-Host "  Running in LIVE mode - changes will be applied." -ForegroundColor Green
        }
        Write-Host ""
    }
    
    # API URL
    $defaultApiUrl = "https://api.blackpointcyber.com"
    $apiUrlInput = Read-Host -Prompt "Enter API URL (press Enter for default: $defaultApiUrl)"
    $apiUrl = if ([string]::IsNullOrWhiteSpace($apiUrlInput)) { $defaultApiUrl } else { $apiUrlInput.TrimEnd('/') }
    Write-Host "  Using API URL: $apiUrl" -ForegroundColor Gray
    Write-Host ""
    
    # API Token (secure input)
    $apiKey = Get-SecureInput -Prompt "Enter your API Key" -AsSecureString
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        Write-Status "API Key is required. Exiting." -Type Error
        return
    }
    Write-Host "  API Key: ****$(($apiKey)[-4..-1] -join '')" -ForegroundColor Gray
    Write-Host ""
   
    # -------------------------------------------------------------------------
    # STEP 2: Validate API connection and fetch tenants
    # -------------------------------------------------------------------------
    
    Write-Status "Validating API connection..." -Type Progress
    
    try {
        $tenants = Get-AllTenants -BaseUrl $apiUrl -ApiKey $apiKey
    }
    catch {
        Write-Status "Failed to fetch tenants: $_" -Type Error
        return
    }
    
    if ($tenants.Count -eq 0) {
        Write-Status "No tenants found. Check your API key permissions." -Type Error
        return
    }
   
    # -------------------------------------------------------------------------
    # List Tenants Option
    # -------------------------------------------------------------------------

    Write-Host ""
    $listTenant = Read-Host -Prompt "A reference Tenant will need to be provided. If you already have the Tenant ID, this can be skipped. List Tenants? [yes/no]"
    if ($listTenant -in @("yes", "y", "Y", "Yes", "YES")) {
        Write-Host ""
        Write-Host "Available Tenants:" -ForegroundColor White
        Write-Host ("-" * 80) -ForegroundColor Gray
        Write-Host ("Tenant Name".PadRight(40) + "Tenant ID") -ForegroundColor White
        Write-Host ("-" * 80) -ForegroundColor Gray
        foreach ($data in $tenants) {
            Write-Host ($data.name.PadRight(40) + $data.id) -ForegroundColor Gray
        }
        Write-Host ("-" * 80) -ForegroundColor Gray
    }
    else {
        Write-Host "  Listing Tenants skipped." -ForegroundColor Green
    }
    Write-Host ""

    # -------------------------------------------------------------------------
    # Template Tenant Selection
    # -------------------------------------------------------------------------

    $templateTenantId = Read-Host -Prompt "Enter the Template Tenant ID (the tenant with the ideal notification settings)"
    if ([string]::IsNullOrWhiteSpace($templateTenantId)) {
        Write-Status "Template Tenant ID is required. Exiting." -Type Error
        return
    }
    
    # Validate GUID format
    try {
        $null = [System.Guid]::Parse($templateTenantId)
    }
    catch {
        Write-Status "Template Tenant ID must be a valid UUID/GUID. Exiting." -Type Error
        return
    }
    Write-Host "  Template Tenant ID: $templateTenantId" -ForegroundColor Gray
    Write-Host ""
    
    # -------------------------------------------------------------------------
    # STEP 3: Find and validate template tenant
    # -------------------------------------------------------------------------
    
    Write-Status "Looking for template tenant..." -Type Progress
    
    $templateTenant = $tenants | Where-Object { $_.id -eq $templateTenantId }
    
    if (-not $templateTenant) {
        Write-Status "Template tenant with ID '$templateTenantId' not found in your accessible tenants." -Type Error
        Write-Status "Available tenants:" -Type Info
        $tenants | Select-Object -First 10 | ForEach-Object {
            Write-Host "  - $($_.name) ($($_.id))" -ForegroundColor Gray
        }
        if ($tenants.Count -gt 10) {
            Write-Host "  ... and $($tenants.Count - 10) more" -ForegroundColor Gray
        }
        return
    }
    
    Write-Status "Found template tenant: '$($templateTenant.name)'" -Type Success
    
    # -------------------------------------------------------------------------
    # STEP 4: Get template tenant's block status
    # -------------------------------------------------------------------------
    
    Write-Status "Fetching block status for template tenant '$($templateTenant.name)'..." -Type Progress
    
    $templateBlockStatus = Get-TenantBlockStatus -BaseUrl $apiUrl -ApiKey $apiKey -TenantId $templateTenantId -TenantName $templateTenant.name
    
    Write-Host ""
    Write-Status "Template tenant notification block status:" -Type Info
    foreach ($type in $CloudMdrNotificationTypes) {
        $status = $templateBlockStatus[$type]
        $statusText = if ($status -eq $true) { "BLOCKED" } elseif ($status -eq $false) { "ALLOWED" } else { "UNKNOWN" }
        $color = if ($status -eq $true) { "Red" } elseif ($status -eq $false) { "Green" } else { "Yellow" }
        Write-Host "  - ${type}: $statusText" -ForegroundColor $color
    }
    Write-Host ""
    
    # -------------------------------------------------------------------------
    # STEP 4b: Allow user to customize desired state
    # -------------------------------------------------------------------------
    
    $customizeSettings = Read-Host -Prompt "Do you want to customize which notifications should be blocked/allowed? [yes/no]"
    
    if ($customizeSettings -in @("yes", "y", "Y", "Yes", "YES")) {
        Write-Host ""
        Write-Host "For each notification type, enter 'block' or 'allow' (or press Enter to keep template setting):" -ForegroundColor White
        Write-Host ""
        
        $customBlockStatus = @{}
        foreach ($type in $CloudMdrNotificationTypes) {
            $currentSetting = if ($templateBlockStatus[$type] -eq $true) { "blocked" } else { "allowed" }
            $input = Read-Host -Prompt "  $type (current: $currentSetting)"
            
            if ($input -in @("block", "blocked", "b", "B")) {
                $customBlockStatus[$type] = $true
            }
            elseif ($input -in @("allow", "allowed", "a", "A", "unblock", "u", "U")) {
                $customBlockStatus[$type] = $false
            }
            else {
                # Keep template setting
                $customBlockStatus[$type] = $templateBlockStatus[$type]
            }
        }
        
        # Update template block status with custom settings
        $templateBlockStatus = $customBlockStatus
        
        Write-Host ""
        Write-Status "Updated notification settings to apply:" -Type Info
        foreach ($type in $CloudMdrNotificationTypes) {
            $status = $templateBlockStatus[$type]
            $statusText = if ($status -eq $true) { "BLOCKED" } elseif ($status -eq $false) { "ALLOWED" } else { "UNKNOWN" }
            $color = if ($status -eq $true) { "Red" } elseif ($status -eq $false) { "Green" } else { "Yellow" }
            Write-Host "  - ${type}: $statusText" -ForegroundColor $color
        }
        Write-Host ""
    }
    
    # Check for any unknown statuses
    $unknownTypes = $templateBlockStatus.GetEnumerator() | Where-Object { $_.Value -eq $null }
    if ($unknownTypes) {
        Write-Status "Warning: Could not determine block status for some notification types." -Type Warning
        foreach ($unknown in $unknownTypes) {
            Write-Host "  - $($unknown.Key)" -ForegroundColor Yellow
        }
        $continueAnyway = Read-Host -Prompt "Continue anyway? (yes/no)"
        if ($continueAnyway -notin @("yes", "y")) {
            Write-Status "Operation cancelled." -Type Warning
            return
        }
    }
    
    # -------------------------------------------------------------------------
    # Confirmation
    # -------------------------------------------------------------------------
    
    Write-Host "--- Ready to Execute ---" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Summary:" -ForegroundColor White
    Write-Host "  API URL:           $apiUrl" -ForegroundColor Gray
    Write-Host "  Template Tenant:   $($templateTenant.name) ($templateTenantId)" -ForegroundColor Gray
    Write-Host "  Tenants to update: $($tenants.Count - 1)" -ForegroundColor Gray
    Write-Host "  Mode:              $(if ($isDryRun) { 'DRY-RUN (no changes)' } else { 'LIVE (changes will be applied)' })" -ForegroundColor $(if ($isDryRun) { 'Yellow' } else { 'Green' })
    Write-Host ""
    Write-Host "Settings to apply:" -ForegroundColor White
    foreach ($type in $CloudMdrNotificationTypes) {
        $status = $templateBlockStatus[$type]
        $statusText = if ($status -eq $true) { "BLOCK" } elseif ($status -eq $false) { "ALLOW" } else { "SKIP" }
        Write-Host "  - ${type}: $statusText" -ForegroundColor Gray
    }
    Write-Host ""
    
    $confirm = Read-Host -Prompt "Do you want to proceed? (yes/no)"
    if ($confirm -notin @("yes", "y", "Y", "Yes", "YES")) {
        Write-Status "Operation cancelled by user." -Type Warning
        return
    }
    
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Starting Execution" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    
    # -------------------------------------------------------------------------
    # STEP 5: Process each tenant
    # -------------------------------------------------------------------------
    
    # Filter out the template tenant
    $tenantsToProcess = $tenants | Where-Object { $_.id -ne $templateTenantId }
    
    Write-Status "Processing $($tenantsToProcess.Count) tenants (excluding template)..." -Type Progress
    Write-Host ""
    
    # Statistics
    $stats = @{
        Processed      = 0
        BlocksAdded    = 0
        BlocksRemoved  = 0
        NoChangeNeeded = 0
        Errors         = 0
    }
    
    $tenantIndex = 0
    foreach ($tenant in $tenantsToProcess) {
        $tenantIndex++
        $percentComplete = [math]::Round(($tenantIndex / $tenantsToProcess.Count) * 100, 1)
        
        Write-Status "[$tenantIndex/$($tenantsToProcess.Count)] ($percentComplete%) Processing tenant: '$($tenant.name)'" -Type Progress
        
        # Get current block status for this tenant
        $currentBlockStatus = Get-TenantBlockStatus -BaseUrl $apiUrl -ApiKey $apiKey -TenantId $tenant.id -TenantName $tenant.name
        
        $tenantChanges = 0
        
        foreach ($notificationType in $CloudMdrNotificationTypes) {
            $desiredBlocked = $templateBlockStatus[$notificationType]
            $currentBlocked = $currentBlockStatus[$notificationType]
            
            # Skip if we couldn't determine either status
            if ($null -eq $desiredBlocked) {
                Write-Status "  Skipping $notificationType (no desired state defined)" -Type Warning
                continue
            }
            
            if ($null -eq $currentBlocked) {
                Write-Status "  Skipping $notificationType (unable to determine current status)" -Type Warning
                continue
            }
            
            Write-Status "  $notificationType - Current: $(if ($currentBlocked) {'BLOCKED'} else {'ALLOWED'}), Desired: $(if ($desiredBlocked) {'BLOCKED'} else {'ALLOWED'})" -Type Debug
            
            # Check if change is needed
            if ($desiredBlocked -eq $currentBlocked) {
                # No change needed
                Write-Status "  $notificationType - Already in desired state" -Type Debug
                continue
            }
            
            if ($desiredBlocked -eq $true -and $currentBlocked -eq $false) {
                # Need to block
                if ($isDryRun) {
                    Write-DryRunAction "Would BLOCK $notificationType"
                    $stats.BlocksAdded++
                    $tenantChanges++
                }
                else {
                    $success = Set-NotificationBlocked -BaseUrl $apiUrl -ApiKey $apiKey -TenantId $tenant.id -EmailType $notificationType -IsDryRun $false
                    if ($success) {
                        Write-Host "    BLOCKED $notificationType" -ForegroundColor Red
                        $stats.BlocksAdded++
                        $tenantChanges++
                    }
                    else {
                        $stats.Errors++
                    }
                }
            }
            elseif ($desiredBlocked -eq $false -and $currentBlocked -eq $true) {
                # Need to unblock
                if ($isDryRun) {
                    Write-DryRunAction "Would UNBLOCK $notificationType"
                    $stats.BlocksRemoved++
                    $tenantChanges++
                }
                else {
                    $success = Set-NotificationUnblocked -BaseUrl $apiUrl -ApiKey $apiKey -TenantId $tenant.id -EmailType $notificationType -IsDryRun $false
                    if ($success) {
                        Write-Host "    UNBLOCKED $notificationType" -ForegroundColor Green
                        $stats.BlocksRemoved++
                        $tenantChanges++
                    }
                    else {
                        $stats.Errors++
                    }
                }
            }
        }
        
        if ($tenantChanges -eq 0) {
            Write-Host "    No changes needed" -ForegroundColor Gray
            $stats.NoChangeNeeded++
        }
        
        $stats.Processed++
    }
    
    # -------------------------------------------------------------------------
    # STEP 6: Summary Report
    # -------------------------------------------------------------------------
    
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Execution Complete" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    
    if ($isDryRun) {
        Write-Host "  *** DRY-RUN MODE - No changes were made ***" -ForegroundColor Yellow
        Write-Host ""
    }
    
    Write-Host "Summary Report:" -ForegroundColor White
    Write-Host "  Template Tenant:     $($templateTenant.name)" -ForegroundColor Gray
    Write-Host "  Tenants Processed:   $($stats.Processed)" -ForegroundColor Gray
    Write-Host "  Blocks Added:        $($stats.BlocksAdded)" -ForegroundColor $(if ($stats.BlocksAdded -gt 0) { 'Yellow' } else { 'Gray' })
    Write-Host "  Blocks Removed:      $($stats.BlocksRemoved)" -ForegroundColor $(if ($stats.BlocksRemoved -gt 0) { 'Yellow' } else { 'Gray' })
    Write-Host "  No Changes Needed:   $($stats.NoChangeNeeded)" -ForegroundColor Gray
    Write-Host "  Errors:              $($stats.Errors)" -ForegroundColor $(if ($stats.Errors -gt 0) { 'Red' } else { 'Gray' })
    Write-Host ""
    
    if ($stats.Errors -gt 0) {
        Write-Status "Completed with $($stats.Errors) error(s). Review the log above for details." -Type Warning
    }
    else {
        Write-Status "Completed successfully!" -Type Success
    }
    
    Write-Host ""
}

# Run the main function
Main
