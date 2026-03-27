"""Prompt: Onboard a new device group."""

from __future__ import annotations

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    @server.prompt(
        name="onboard_device_group",
        description="Guided workflow to create and configure a new device group with policies.",
    )
    def onboard_device_group(group_name: str) -> str:
        return f"""Onboard a new device group called "{group_name}". Follow these steps:

1. **List existing groups**: Use `list_server_groups` to review current group structure and find the appropriate parent group.

2. **Review existing policies**: Use `policy_catalog` to see available policies that could be assigned to the new group.

3. **Check worklet catalog**: Use `search_worklet_catalog` to find pre-built worklets relevant to the new group's purpose.

4. **Create the group**: Use `create_server_group` with:
   - name: "{group_name}"
   - refresh_interval: 1440 (24 hours, adjust as needed)
   - parent_server_group_id: (the appropriate parent from step 1)

5. **Assign policies**: Use `apply_policy_changes` to update existing policies to include the new group, or create new policies targeting this group.

6. **Verify configuration**: Use `get_server_group` to confirm the group was created correctly with the right parent and policies.

7. **Review policy schedule syntax**: Check resource://policies/schedule-syntax for help setting up schedules, and resource://policies/quick-start for policy templates.

Present a summary with:
- New group ID and configuration
- Assigned policies
- Recommended next steps (e.g., moving devices into the group, setting up webhooks for monitoring)"""
