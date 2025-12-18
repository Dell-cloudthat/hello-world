# Cloud MDR Notification Mirror Tool - User Guide

## Overview

This guide explains how to use the **Cloud MDR Notification Mirror Tool** to manage email notification settings across all your tenants at once, saving you time and ensuring consistency.

---

## What Does This Tool Do?

Imagine you manage 50 different client organizations (tenants) in CompassOne. Each tenant can receive email notifications about security events like:

- **Google Workspace alerts** (CloudResponseNotification)
- **Cisco Duo alerts** (CiscoDuoNotification)
- **Microsoft 365 alerts** (MS365DefenseNotification)
- **Microsoft 365 permission change alerts** (MS365DefenseNewPermsNotification)

Normally, you would need to log into each tenant individually and configure these settings one by one. That's 50 different configurations!

**This tool automates that process.** You set up one tenant the way you want it (your "template"), and the tool copies those settings to all your other tenants automatically.

---

## What is an API? (Simple Explanation)

Think of an **API** (Application Programming Interface) as a **waiter in a restaurant**:

1. **You** (the customer) want to order food
2. **The waiter** (the API) takes your order to the kitchen
3. **The kitchen** (the server/system) prepares your food
4. **The waiter** brings the food back to you

In technical terms:
- **You** = This PowerShell script
- **The waiter** = The Blackpoint API
- **The kitchen** = Blackpoint's servers that store your tenant settings

The script "talks" to Blackpoint's systems using the API to read and change notification settings, just like you would do manually in the web interface—but much faster.

---

## Key Terms Explained

| Term | What It Means |
|------|---------------|
| **Tenant** | A client organization you manage in CompassOne |
| **Template Tenant** | The tenant whose settings you want to copy to others |
| **API Key** | A secret password that proves you're authorized to make changes |
| **Blocked** | The notification is turned OFF (you won't receive these emails) |
| **Allowed** | The notification is turned ON (you will receive these emails) |
| **Dry-Run** | A practice mode that shows what would happen without making real changes |

---

## When Would I Use This Tool?

### Common Scenarios:

1. **New Partner Onboarding**
   > "I just added 20 new tenants and need to configure their notification settings to match our standards."

2. **Policy Changes**
   > "We decided to stop receiving Cisco Duo alerts for all tenants. I need to update 100+ tenants."

3. **Consistency Check**
   > "I want to make sure all our tenants have the same notification settings."

4. **Time Savings**
   > "I don't have time to manually configure each tenant one by one."

---

## Before You Start

### What You'll Need:

1. **A Computer with PowerShell**
   - Windows: Already installed (search for "PowerShell" in Start menu)
   - Mac/Linux: Install [PowerShell Core](https://docs.microsoft.com/en-us/powershell/scripting/install/installing-powershell)

2. **Your API Key**
   - This is like a password that lets the script access your account
   - Get it from your CompassOne administrator or API settings page
   - **Keep it secret!** Never share your API key

3. **Your Template Tenant ID**
   - The unique identifier (looks like: `345f28b8-b4e2-4521-9202-d1de87ae6ad1`)
   - The script can show you a list of all your tenants if you don't know the ID

---

## How to Use the Tool (Step-by-Step)

### Step 1: Open PowerShell

- **Windows**: Press `Win + X`, then select "Windows PowerShell"
- **Mac/Linux**: Open Terminal and type `pwsh`

### Step 2: Navigate to the Script Location

```powershell
cd C:\path\to\your\scripts
```

### Step 3: Run the Script

**Option A: Practice Mode (Recommended for First Time)**
```powershell
.\Mirror-CloudMdrNotifications.ps1 -DryRun
```
This shows what would happen without making any changes.

**Option B: Live Mode (Makes Real Changes)**
```powershell
.\Mirror-CloudMdrNotifications.ps1
```

### Step 4: Follow the Prompts

The script will ask you questions. Here's what to expect:

```
Run in dry-run mode? (yes = preview only, no = apply changes) [yes/no]
```
> Type `yes` to practice, `no` to make real changes

```
Enter API URL (press Enter for default: https://api.blackpointcyber.com)
```
> Just press Enter to use the default

```
Enter your API Key
```
> Paste your API key (it will be hidden for security)

```
List Tenants? [yes/no]
```
> Type `yes` to see all your tenants and their IDs

```
Enter the Template Tenant ID
```
> Paste the ID of the tenant you want to copy settings FROM

### Step 5: Review and Confirm

The script will show you:
- The template tenant's current settings
- What changes will be made
- How many tenants will be updated

Type `yes` to proceed or `no` to cancel.

---

## Understanding the Results

After the script runs, you'll see a summary like this:

```
Summary Report:
  Template Tenant:     Acme Corporation
  Tenants Processed:   47
  Blocks Added:        12
  Blocks Removed:      8
  No Changes Needed:   27
  Errors:              0
```

| Metric | What It Means |
|--------|---------------|
| **Tenants Processed** | How many tenants the script checked |
| **Blocks Added** | How many notifications were turned OFF |
| **Blocks Removed** | How many notifications were turned ON |
| **No Changes Needed** | Tenants that already had correct settings |
| **Errors** | Problems that occurred (0 is good!) |

---

## Notification Types Explained

| Notification Type | What Triggers It |
|-------------------|------------------|
| **CloudResponseNotification** | Security events detected in Google Workspace (Gmail, Google Drive, etc.) |
| **CiscoDuoNotification** | Security events from Cisco Duo multi-factor authentication |
| **MS365DefenseNotification** | Security events in Microsoft 365 (Outlook, OneDrive, SharePoint, etc.) |
| **MS365DefenseNewPermsNotification** | When new permissions are granted in Microsoft 365 applications |

### Blocked vs. Allowed

- **BLOCKED** = You will NOT receive email notifications for this type
- **ALLOWED** = You WILL receive email notifications for this type

---

## Frequently Asked Questions

### Is this safe to use?

Yes! The script includes several safety features:
- **Dry-run mode** lets you preview changes first
- **Confirmation prompts** before making changes
- **Detailed logging** so you can see exactly what happened

### Can I undo changes?

Yes. Simply run the script again with a different template tenant, or manually change settings in the CompassOne web interface.

### What if I make a mistake?

If you're in dry-run mode, nothing actually changes. If you made real changes, you can:
1. Run the script again with correct settings
2. Manually fix settings in the web interface

### How long does it take?

It depends on how many tenants you have:
- 10 tenants: ~1-2 minutes
- 50 tenants: ~5-10 minutes
- 100+ tenants: ~15-20 minutes

The script includes delays between actions to avoid overloading the system.

### What if the script stops with an error?

Common issues and solutions:

| Error | Solution |
|-------|----------|
| "Authentication failed" | Check that your API key is correct |
| "Rate limit exceeded" | Wait a few minutes and try again |
| "Tenant not found" | Verify the tenant ID is correct |

---

## Getting Help

If you encounter issues:

1. **Run in dry-run mode first** to test without making changes
2. **Check your API key** is valid and has correct permissions
3. **Contact Blackpoint Support** if problems persist

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────┐
│           CLOUD MDR NOTIFICATION MIRROR                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  PRACTICE MODE (no changes):                            │
│  .\Mirror-CloudMdrNotifications.ps1 -DryRun             │
│                                                         │
│  LIVE MODE (makes changes):                             │
│  .\Mirror-CloudMdrNotifications.ps1                     │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  WHAT YOU NEED:                                         │
│  ✓ API Key (from your administrator)                   │
│  ✓ Template Tenant ID (or use list feature)            │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  NOTIFICATION TYPES:                                    │
│  • CloudResponseNotification (Google Workspace)         │
│  • CiscoDuoNotification (Cisco Duo)                    │
│  • MS365DefenseNotification (Microsoft 365)            │
│  • MS365DefenseNewPermsNotification (M365 Perms)       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

*Last Updated: December 2024 | Version 1.1.0*
