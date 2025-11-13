"""Policy-related resources for Automox MCP."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_policy_resources(server: FastMCP) -> None:
    """Register policy schema and example resources."""

    @server.resource(
        "resource://policies/quick-start",
        name="Policy Quick Start Templates",
        description="Copy-paste templates for creating common policy types",
        mime_type="application/json",
    )
    def get_policy_quick_start() -> dict[str, Any]:
        """
        Quick-start templates for common policy creation tasks.

        Use these as starting points and customize as needed.
        """
        return {
            "patch_policy_by_software_name": {
                "description": "Patch a specific software by name (e.g., Chrome, Firefox, Zoom)",
                "template": {
                    "action": "create",
                    "policy": {
                        "name": "Auto-Patch [SOFTWARE_NAME]",
                        "organization_id": 0,  # Replace with your org ID
                        "policy_type_name": "patch",
                        "configuration": {
                            "patch_rule": "filter",
                            "filters": ["*[SOFTWARE_NAME]*"],
                            "auto_patch": True,
                            "auto_reboot": False,
                            "notify_user": True,
                        },
                        "schedule": {"days": ["weekdays"], "time": "02:00"},
                        "server_groups": [],  # Replace with your group IDs
                        "notes": "Automatically patches [SOFTWARE_NAME]",
                    },
                },
                "example": {
                    "action": "create",
                    "policy": {
                        "name": "Auto-Patch Google Chrome",
                        "organization_id": 106820,
                        "policy_type_name": "patch",
                        "configuration": {
                            "patch_rule": "filter",
                            "filters": ["*Google Chrome*"],
                            "auto_patch": True,
                            "auto_reboot": False,
                            "notify_user": True,
                        },
                        "schedule": {"days": ["weekdays"], "time": "02:00"},
                        "server_groups": [366711],
                        "notes": "Automatically patches Google Chrome on weekdays at 2 AM",
                    },
                },
            },
            "patch_all_software": {
                "description": "Patch all available software on devices",
                "template": {
                    "action": "create",
                    "policy": {
                        "name": "Patch All Software",
                        "organization_id": 0,  # Replace with your org ID
                        "policy_type_name": "patch",
                        "configuration": {
                            "patch_rule": "all",
                            "auto_patch": True,
                            "auto_reboot": True,
                            "notify_reboot_user": True,
                        },
                        "schedule": {"days": ["weekend"], "time": "01:00"},
                        "server_groups": [],  # Replace with your group IDs
                        "notes": "Patches all software on weekends",
                    },
                },
            },
            "critical_patches_only": {
                "description": "Apply only critical severity patches",
                "template": {
                    "action": "create",
                    "policy": {
                        "name": "Critical Patches Only",
                        "organization_id": 0,  # Replace with your org ID
                        "policy_type_name": "patch",
                        "configuration": {
                            "patch_rule": "severity",
                            "severity": "critical",
                            "auto_patch": True,
                            "auto_reboot": True,
                        },
                        "schedule": {"days": ["monday"], "time": "03:00"},
                        "server_groups": [],  # Replace with your group IDs
                        "notes": "Applies critical patches every Monday at 3 AM",
                    },
                },
            },
            "using_filter_name_shortcut": {
                "description": (
                    "Use filter_name shortcut for single software (auto-wrapped with wildcards)"
                ),
                "note": (
                    "The MCP will automatically convert filter_name into "
                    "configuration.filters with wildcards and set "
                    "filter_type='include'"
                ),
                "template": {
                    "action": "create",
                    "policy": {
                        "name": "Patch [SOFTWARE]",
                        "organization_id": 0,
                        "policy_type_name": "patch",
                        "configuration": {
                            "filter_name": "Chrome",  # Automatically becomes filters: ["*Chrome*"]
                            "auto_patch": True,
                            "auto_reboot": False,
                            "notify_user": True,
                        },
                        "schedule": {"days": ["weekdays"], "time": "02:00"},
                        "server_groups": [],
                    },
                },
                "example": {
                    "action": "create",
                    "policy": {
                        "name": "Auto-Patch Firefox",
                        "organization_id": 106820,
                        "policy_type_name": "patch",
                        "configuration": {
                            "filter_name": "Firefox",
                            "auto_patch": True,
                            "auto_reboot": False,
                            "notify_user": True,
                        },
                        "schedule": {"days": ["weekdays"], "time": "02:00"},
                        "server_groups": [366711],
                        "notes": "Automatically patches Firefox on weekdays at 2 AM",
                    },
                },
            },
            "important_reminders": [
                (
                    "ALWAYS check resource://servergroups/list to get valid "
                    "server_group IDs before creating policies"
                ),
                (
                    "For patch policies: auto_patch, auto_reboot, and "
                    "notify_user go INSIDE the configuration object"
                ),
                "The MCP will auto-fix if you accidentally place them at the top level",
                (
                    "Use filter_name inside configuration for single-package "
                    "patches (auto-wrapped with wildcards)"
                ),
                (
                    "The MCP will auto-fix if you place filter_name at top "
                    "level instead of inside configuration"
                ),
                "Use schedule block with friendly syntax: {'days': ['weekdays'], 'time': '02:00'}",
                (
                    "Scheduling: If you provide days, the MCP will auto-set "
                    "weeks=62 (all 5 weeks) and months=8190 (all 12 months)"
                ),
                (
                    "You can override weeks/months if you want the policy to "
                    "run only in specific weeks/months"
                ),
                "filter_type is automatically set to 'include' when using filter_name or filters",
            ],
        }

    @server.resource(
        "resource://policies/schema",
        name="Policy Schema Reference",
        description=(
            "Complete Automox policy schema with required fields, examples, and best practices"
        ),
        mime_type="application/json",
    )
    def get_policy_schema() -> dict[str, Any]:
        """
        Comprehensive policy schema for creating and updating Automox policies.

        This resource provides the complete structure for all supported policy types,
        including required fields, optional parameters, and working examples.
        """
        return {
            "overview": {
                "description": (
                    "Automox supports three policy types: patch, custom, and required_software"
                ),
                "supported_types": ["patch", "custom", "required_software"],
                "operations": ["create", "update"],
                "notes": [
                    "Updates require the policy 'id' field",
                    "schedule_days uses a bitmask (Sunday=1, Monday=2, Tuesday=4, etc.)",
                    "You can use friendly schedule syntax with a 'schedule' block",
                    "Filter names can be specified using 'filter_name' or 'filter_names' shortcuts",
                ],
            },
            "common_fields": {
                "required_for_all": {
                    "name": "str - Policy name",
                    "organization_id": "int - Organization ID",
                    "policy_type_name": "str - One of: patch, custom, required_software",
                },
                "optional_for_all": {
                    "notes": "str - Policy description/notes",
                    "enabled": "bool - Whether policy is active (default: true)",
                    "schedule_days": "int - Bitmask of days (1-127 for all 7 days)",
                    "schedule_time": "str - Time in HH:MM format (24-hour)",
                    "schedule_weeks_of_month": (
                        "int - Bitmask for weeks (1-62, default: 62 = all 5 weeks)"
                    ),
                    "schedule_months": (
                        "int - Bitmask for months (1-8190, default: 8190 = all 12 months)"
                    ),
                    "server_groups": "list[int] - List of group IDs to target",
                    "device_filters": "list[dict] - Advanced device filtering",
                    "missed_patch_window": "bool - Run missed patches outside window",
                },
                "important_notes": {
                    "patch_policy_fields": (
                        "For PATCH policies, auto_patch, auto_reboot, notify_user, and "
                        "notify_reboot_user MUST be placed inside the 'configuration' object, "
                        "not at the top level. The MCP will auto-fix this for you if you put "
                        "them at the top level."
                    ),
                    "scheduling_requirement": (
                        "If you provide schedule_days, Automox REQUIRES schedule_weeks_of_month "
                        "AND schedule_months to also be set. The MCP will auto-set these to "
                        "sensible defaults (all 5 weeks=62, all 12 months=8190) if you don't "
                        "provide them."
                    ),
                },
                "read_only_fields": {
                    "note": (
                        "These fields are returned by Automox but cannot be set "
                        "during create/update"
                    ),
                    "fields": [
                        "id",
                        "uuid",
                        "create_time",
                        "server_count",
                        "status",
                        "next_remediation",
                        "policy_uuid",
                        "account_id",
                    ],
                },
            },
            "schedule_helpers": {
                "description": "Use the 'schedule' block for friendly scheduling syntax",
                "example": {
                    "schedule": {
                        "days": ["weekdays"],
                        "time": "02:00",
                        "weeks": [1, 3],
                    }
                },
                "day_options": {
                    "individual": [
                        "sunday",
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                    ],
                    "abbreviations": ["sun", "mon", "tue", "wed", "thu", "fri", "sat"],
                    "groups": {
                        "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "weekend": ["saturday", "sunday"],
                        "all": "All seven days",
                    },
                    "numeric": "0-6 (Sunday=0) or list of numeric indexes",
                },
                "bitmask_values": {
                    "sunday": 1,
                    "monday": 2,
                    "tuesday": 4,
                    "wednesday": 8,
                    "thursday": 16,
                    "friday": 32,
                    "saturday": 64,
                    "example": "weekdays = 2+4+8+16+32 = 62",
                },
            },
            "policy_types": {
                "patch": {
                    "description": "Patch management policies for OS and third-party software",
                    "required_fields": {
                        "name": "Policy name",
                        "organization_id": "Organization ID",
                        "policy_type_name": "Must be 'patch'",
                        "configuration": (
                            "Patch configuration object (required) - must contain "
                            "patch_rule, auto_patch, auto_reboot"
                        ),
                    },
                    "configuration_structure": {
                        "patch_rule": (
                            "str - REQUIRED - Filter type: 'filter', 'all', 'severity', or 'custom'"
                        ),
                        "auto_patch": "bool - REQUIRED - Automatically apply patches",
                        "auto_reboot": "bool - REQUIRED - Automatically reboot after patching",
                        "filters": ("list[str] - Package name patterns (when patch_rule='filter')"),
                        "severity": "str - Patch severity level (when patch_rule='severity')",
                        "os_family": "str - Target OS family",
                        "notify_user": "bool - Notify users before actions",
                        "notify_reboot_user": "bool - Notify users before reboot",
                        "patch_windows": "list[dict] - Custom patch windows",
                    },
                    "examples": {
                        "chrome_patching": {
                            "name": "Chrome Auto-Patch",
                            "organization_id": 123456,
                            "policy_type_name": "patch",
                            "configuration": {
                                "patch_rule": "filter",
                                "filters": ["*Google Chrome*", "*Chrome*"],
                                "auto_patch": True,
                                "auto_reboot": False,
                                "notify_user": True,
                            },
                            "schedule": {
                                "days": ["weekdays"],
                                "time": "02:00",
                            },
                            "server_groups": [366711],
                        },
                        "critical_patches": {
                            "name": "Critical Patches - Weekly",
                            "organization_id": 123456,
                            "policy_type_name": "patch",
                            "configuration": {
                                "patch_rule": "severity",
                                "severity": "critical",
                                "auto_patch": True,
                                "auto_reboot": True,
                            },
                            "schedule_days": 2,
                            "schedule_time": "03:00",
                        },
                        "all_patches": {
                            "name": "Patch All Software",
                            "organization_id": 123456,
                            "policy_type_name": "patch",
                            "configuration": {
                                "patch_rule": "all",
                                "auto_patch": True,
                                "auto_reboot": True,
                                "notify_reboot_user": True,
                            },
                            "schedule": {
                                "days": "weekend",
                                "time": "01:00",
                            },
                        },
                    },
                    "filter_shortcuts": {
                        "description": (
                            "Use filter_name or filter_names for convenience "
                            "(must be inside configuration object)"
                        ),
                        "filter_name": (
                            "str - Single package name (automatically wrapped in wildcards)"
                        ),
                        "filter_names": "list[str] - Multiple package names",
                        "auto_fixes": [
                            (
                                "If filter_name/filter_names is at top level, it will be "
                                "moved into configuration"
                            ),
                            (
                                "If patch_rule is not specified but filters are present, "
                                "patch_rule will be auto-set to 'filter'"
                            ),
                            "filter_type will be auto-set to 'include' if not specified",
                        ],
                        "example": {
                            "using_filter_name": {
                                "filter_name": "Chrome",
                                "result": (
                                    "Automatically becomes configuration.filters = ['*Chrome*']"
                                ),
                            },
                            "using_filter_names": {
                                "filter_names": ["Chrome", "Firefox", "Zoom"],
                                "result": (
                                    "Becomes configuration.filters = "
                                    "['*Chrome*', '*Firefox*', '*Zoom*']"
                                ),
                            },
                        },
                    },
                },
                "custom": {
                    "description": "Custom worklet policies for running arbitrary scripts",
                    "required_fields": {
                        "name": "Policy name",
                        "organization_id": "Organization ID",
                        "policy_type_name": "Must be 'custom'",
                        "configuration": "Custom worklet configuration",
                    },
                    "configuration_structure": {
                        "evaluation_code": "str - Script to check if remediation is needed",
                        "remediation_code": "str - Script to perform remediation",
                        "os_family": "str - Target OS: Windows, Linux, or Mac",
                        "shell_type": "str - Shell to use (depends on os_family)",
                    },
                    "shell_types_by_os": {
                        "Windows": ["PowerShell", "Cmd"],
                        "Mac": ["Bash", "Zsh"],
                        "Linux": ["Bash", "Zsh"],
                    },
                    "examples": {
                        "check_service": {
                            "name": "Ensure Service Running",
                            "organization_id": 123456,
                            "policy_type_name": "custom",
                            "configuration": {
                                "evaluation_code": "systemctl is-active myservice",
                                "remediation_code": "systemctl start myservice",
                                "os_family": "Linux",
                                "shell_type": "Bash",
                            },
                            "schedule": {
                                "days": "all",
                                "time": "06:00",
                            },
                        },
                        "windows_registry": {
                            "name": "Configure Registry Setting",
                            "organization_id": 123456,
                            "policy_type_name": "custom",
                            "configuration": {
                                "evaluation_code": (
                                    "Get-ItemProperty -Path 'HKLM:\\Software\\MyApp' "
                                    "-Name MySetting"
                                ),
                                "remediation_code": (
                                    "Set-ItemProperty -Path 'HKLM:\\Software\\MyApp' "
                                    "-Name MySetting -Value 'Enabled'"
                                ),
                                "os_family": "Windows",
                                "shell_type": "PowerShell",
                            },
                            "schedule_days": 127,
                            "schedule_time": "12:00",
                        },
                    },
                },
                "required_software": {
                    "description": "Ensure specific software packages are installed",
                    "required_fields": {
                        "name": "Policy name",
                        "organization_id": "Organization ID",
                        "policy_type_name": "Must be 'required_software'",
                        "configuration": "Software installation configuration",
                    },
                    "configuration_structure": {
                        "packages": "list[str] - Package names to install",
                        "install_command": "str - Command to install missing packages",
                        "os_family": "str - Target OS family",
                    },
                    "examples": {
                        "essential_tools": {
                            "name": "Required Dev Tools",
                            "organization_id": 123456,
                            "policy_type_name": "required_software",
                            "configuration": {
                                "packages": ["git", "curl", "vim"],
                                "os_family": "Linux",
                            },
                            "schedule": {
                                "days": "weekdays",
                                "time": "00:00",
                            },
                        }
                    },
                },
            },
            "update_operations": {
                "description": "Updating policies requires the policy ID and uses PATCH semantics",
                "required_fields": ["policy_id" or "id within policy object"],
                "two_ways_to_update": {
                    "method_1_recommended": {
                        "description": "Specify policy_id at top level, changes in policy object",
                        "example": {
                            "action": "update",
                            "policy_id": 681186,
                            "policy": {
                                "schedule": {"days": ["weekend"], "time": "02:00"},
                            },
                        },
                    },
                    "method_2_alternative": {
                        "description": "Include id within policy object",
                        "example": {
                            "action": "update",
                            "policy": {
                                "id": 681186,
                                "schedule": {"days": ["weekend"], "time": "02:00"},
                            },
                        },
                    },
                },
                "common_update_examples": {
                    "change_schedule_to_weekends": {
                        "description": "Update a policy to run on weekends only",
                        "operation": {
                            "action": "update",
                            "policy_id": 681186,
                            "policy": {
                                "schedule": {"days": ["weekend"], "time": "02:00"},
                            },
                        },
                    },
                    "change_schedule_to_weekdays": {
                        "description": "Update a policy to run on weekdays",
                        "operation": {
                            "action": "update",
                            "policy_id": 681186,
                            "policy": {
                                "schedule": {"days": ["weekdays"], "time": "02:00"},
                            },
                        },
                    },
                    "rename_policy": {
                        "description": "Change policy name",
                        "operation": {
                            "action": "update",
                            "policy_id": 681186,
                            "policy": {"name": "New Policy Name"},
                        },
                    },
                    "change_target_groups": {
                        "description": "Update which server groups are targeted",
                        "operation": {
                            "action": "update",
                            "policy_id": 681186,
                            "policy": {"server_groups": [123, 456]},
                        },
                    },
                },
                "important_notes": [
                    "Only include fields you want to change in the policy object",
                    "The policy_id is required (either at top level or as 'id' within policy)",
                    "All other fields in policy are optional during updates",
                    "Use friendly schedule syntax: {'days': ['weekend'], 'time': '02:00'}",
                    "The MCP will merge your changes with the existing policy configuration",
                ],
            },
            "device_targeting": {
                "description": "Control which devices a policy applies to",
                "server_groups": {
                    "description": "List of Automox group IDs",
                    "example": {"server_groups": [101, 102, 103]},
                },
                "device_filters": {
                    "description": "Advanced filtering using Automox filter syntax",
                    "structure": [
                        {
                            "type": "group",
                            "server_group_id": 101,
                        },
                        {
                            "type": "tag",
                            "tag_name": "production",
                        },
                    ],
                },
            },
            "best_practices": [
                "Always test new policies on a small group first",
                "Use descriptive names that include the purpose and schedule",
                "Set notify_user=true for policies that might disrupt work",
                "Use auto_reboot sparingly and only during maintenance windows",
                "Leverage schedule.days=['weekdays'] for business-hours policies",
                "Use filter_name shortcut for single-package patch policies",
                (
                    "Test custom worklets' evaluation_code returns proper exit codes "
                    "(0=compliant, 1=needs remediation)"
                ),
            ],
            "common_mistakes": [
                "Forgetting to include 'configuration' for patch policies",
                (
                    "Placing auto_patch, auto_reboot, notify_user at the "
                    "TOP LEVEL instead of INSIDE configuration for patch "
                    "policies (the MCP will auto-fix this for you)"
                ),
                (
                    "Forgetting to include auto_patch and auto_reboot inside "
                    "configuration for patch policies (they are REQUIRED)"
                ),
                "Using schedule_days as a list instead of a bitmask",
                "Mixing schedule_days/schedule_time with schedule block (use one approach)",
                "Including read-only fields like 'id' or 'uuid' during create operations",
                "Not wrapping filter patterns in wildcards (use filter_name to auto-wrap)",
            ],
        }

    @server.resource(
        "resource://policies/schedule-syntax",
        name="Policy Schedule Syntax",
        description="Detailed guide for Automox policy scheduling syntax and bitmask calculations",
        mime_type="text/plain",
    )
    def get_schedule_syntax() -> str:
        """Detailed explanation of Automox policy scheduling."""
        return """# Automox Policy Schedule Syntax

## Overview
Automox policies use schedule_days (bitmask) and schedule_time (24-hour format) for scheduling.
FastMCP provides a friendly 'schedule' helper block that automatically converts to bitmasks.

## IMPORTANT: Scheduling Requirements
Automox requires ALL THREE of these fields when scheduling a policy:
1. **schedule_days** - Which days of the week (bitmask 1-127, where 127 = all 7 days)
2. **schedule_weeks_of_month** - Which weeks of the month (bitmask 1-62, where
   1=first week, 2=second, 4=third, 8=fourth, 16=fifth)
3. **schedule_months** - Which months of the year (bitmask 1-8190, where each bit
   represents a month)

If you only provide schedule_days, the MCP will automatically set:
- schedule_weeks_of_month = 62 (all 5 weeks with trailing zero)
- schedule_months = 8190 (all 12 months with trailing zero)

This means your policy will run on the specified days EVERY week of EVERY month.

Reference: https://developer.automox.com/developer-portal/policy_filters_schedule/

## Friendly Schedule Syntax (Recommended)

Use the 'schedule' block in your policy:

```json
{
  "schedule": {
    "days": ["weekdays"],
    "time": "02:00"
  }
}
```

### Day Options:

**Individual Days:**
- "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"
- Abbreviations: "sun", "mon", "tue", "wed", "thu", "fri", "sat"

**Day Groups:**
- "weekdays" = Monday through Friday
- "weekend" = Saturday and Sunday
- "all" or "everyday" = All seven days

**Numeric:**
- 0-6 (where 0=Sunday, 1=Monday, etc.)
- Example: [1, 3, 5] = Monday, Wednesday, Friday

**Mix and Match:**
```json
"days": ["monday", "wednesday", "friday"]
"days": ["weekdays"]
"days": [1, 3, 5]
```

### Time Format:
- 24-hour format: "HH:MM"
- Examples: "02:00", "14:30", "23:45"

## Bitmask Format (Advanced)

**IMPORTANT**: Automox uses an 8-bit pattern with a "trailing zero" at bit 0 (always unused).
The bit positions use an unusual ordering (not chronological):

**Bit Position to Day Mapping:**
- Bit 7 (value 128) = Sunday
- Bit 6 (value 64)  = Saturday
- Bit 5 (value 32)  = Friday
- Bit 4 (value 16)  = Thursday
- Bit 3 (value 8)   = Wednesday
- Bit 2 (value 4)   = Tuesday
- Bit 1 (value 2)   = Monday
- Bit 0 (value 1)   = Trailing zero (unused/always 0)

**Day to Value (for calculations):**
- Monday    = 2
- Tuesday   = 4
- Wednesday = 8
- Thursday  = 16
- Friday    = 32
- Saturday  = 64
- Sunday    = 128

### Calculating Bitmasks:

**Weekdays (Mon-Fri):**
2 + 4 + 8 + 16 + 32 = 62 (binary: 00111110)

**Weekend (Sat-Sun):**
64 + 128 = 192 (binary: 11000000)

**Every Day:**
2 + 4 + 8 + 16 + 32 + 64 + 128 = 254 (binary: 11111110)

**Monday, Wednesday, Friday:**
2 + 8 + 32 = 42 (binary: 00101010)

## Examples

### Example 1: Weekday Morning Patches
```json
{
  "name": "Morning Patches",
  "schedule": {
    "days": ["weekdays"],
    "time": "02:00"
  }
}
```
This becomes: schedule_days=62, schedule_time="02:00"

### Example 2: Weekend Maintenance
```json
{
  "schedule": {
    "days": ["weekend"],
    "time": "01:00"
  }
}
```
This becomes: schedule_days=192, schedule_time="01:00"

### Example 3: Specific Days
```json
{
  "schedule": {
    "days": ["monday", "wednesday", "friday"],
    "time": "03:30"
  }
}
```
This becomes: schedule_days=42, schedule_time="03:30"

### Example 4: Direct Bitmask (if needed)
```json
{
  "schedule_days": 254,
  "schedule_time": "00:00"
}
```
Runs every day at midnight.

## Best Practices

1. Use the friendly 'schedule' block for better readability
2. Avoid scheduling during business hours unless using notify_user
3. Stagger policies to avoid overwhelming devices
4. Use "weekdays" for regular maintenance
5. Reserve "weekend" for potentially disruptive operations

## Common Mistakes

❌ Don't mix schedule block with schedule_days:
```json
{
  "schedule": {"days": ["weekdays"]},
  "schedule_days": 62  // Remove this - it's redundant
}
```

❌ Don't use 12-hour time format:
```json
"time": "2:00 PM"  // Wrong
"time": "14:00"    // Correct
```

❌ Don't use lowercase in direct bitmask:
```json
"schedule_days": "weekdays"  // Wrong - must be integer
"schedule_days": 62          // Correct
```
"""
