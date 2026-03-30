"""
Email tool — lets the agent manage inboxes and send/read emails via AgentMail.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from app.tools.base import BaseTool
from app.services.agentmail_service import agentmail_service


class EmailTool(BaseTool):
    name = "email"
    description = (
        "Manage agent email inboxes and send/receive emails. "
        "Use this tool to create inboxes, send emails, read incoming messages, "
        "sign up for platforms using a dedicated agent email address, "
        "and communicate with other agents or users."
    )
    schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "create_inbox",
                    "list_inboxes",
                    "get_inbox",
                    "delete_inbox",
                    "send_email",
                    "list_messages",
                    "get_message",
                    "reply",
                    "delete_message",
                ],
                "description": "Email operation to perform",
            },
            "inbox_id": {"type": "string", "description": "Inbox ID for inbox-specific operations"},
            "username": {"type": "string", "description": "Desired username for new inbox"},
            "display_name": {"type": "string", "description": "Display name for the inbox"},
            "to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email addresses"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Plain-text email body"},
            "html": {"type": "string", "description": "Optional HTML email body"},
            "cc": {"type": "array", "items": {"type": "string"}, "description": "CC recipients"},
            "message_id": {"type": "string", "description": "Message ID for get/reply/delete"},
            "limit": {"type": "integer", "description": "Max messages to list", "default": 20},
        },
        "required": ["operation"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        operation = input.get("operation", "")

        if not agentmail_service.available:
            return {
                "success": False,
                "result": "AgentMail is not configured. Please add an AgentMail API key in Settings.",
                "error": "AgentMail API key not set",
            }

        try:
            if operation == "create_inbox":
                result = await agentmail_service.create_inbox(
                    username=input.get("username"),
                    display_name=input.get("display_name"),
                )
                return {
                    "success": result["success"],
                    "result": f"Created inbox: {result.get('address', result.get('inbox_id', '?'))}",
                    "data": result,
                }

            elif operation == "list_inboxes":
                result = await agentmail_service.list_inboxes()
                inboxes = result.get("inboxes", [])
                summary = "\n".join(
                    f"- {i.get('address') or i.get('email', '?')} (id: {i.get('id') or i.get('inbox_id', '?')})"
                    for i in inboxes
                ) or "No inboxes found."
                return {"success": True, "result": summary, "data": result}

            elif operation == "get_inbox":
                result = await agentmail_service.get_inbox(input.get("inbox_id", ""))
                return {"success": result["success"], "result": json.dumps(result, indent=2), "data": result}

            elif operation == "delete_inbox":
                result = await agentmail_service.delete_inbox(input.get("inbox_id", ""))
                return {
                    "success": result["success"],
                    "result": "Inbox deleted." if result["success"] else result.get("error", "Failed"),
                    "data": result,
                }

            elif operation in ("send_email", "reply"):
                inbox_id = input.get("inbox_id", "")
                to = input.get("to", [])
                subject = input.get("subject", "(no subject)")
                body = input.get("body", "")
                if not inbox_id:
                    return {"success": False, "result": "inbox_id is required", "error": "Missing inbox_id"}
                if not to:
                    return {"success": False, "result": "'to' recipients are required", "error": "Missing to"}
                result = await agentmail_service.send_message(
                    inbox_id, to, subject, body,
                    html=input.get("html"),
                    cc=input.get("cc"),
                    reply_to_id=input.get("message_id") if operation == "reply" else None,
                )
                if result["success"]:
                    return {
                        "success": True,
                        "result": f"Email sent to {', '.join(to)} (message_id: {result.get('message_id', '?')})",
                        "data": result,
                    }
                return {"success": False, "result": result.get("error", "Send failed"), "data": result}

            elif operation == "list_messages":
                inbox_id = input.get("inbox_id", "")
                limit = int(input.get("limit", 20))
                result = await agentmail_service.list_messages(inbox_id, limit=limit)
                messages = result.get("messages", [])
                if not messages:
                    return {"success": True, "result": "No messages in inbox.", "data": result}
                lines = []
                for m in messages:
                    sender = m.get("from") or m.get("sender", "?")
                    subj = m.get("subject", "(no subject)")
                    date = m.get("date") or m.get("created_at", "")
                    mid = m.get("id") or m.get("message_id", "?")
                    lines.append(f"[{mid}] From: {sender} | {subj} | {date}")
                return {"success": True, "result": "\n".join(lines), "data": result}

            elif operation == "get_message":
                inbox_id = input.get("inbox_id", "")
                message_id = input.get("message_id", "")
                result = await agentmail_service.get_message(inbox_id, message_id)
                if not result.get("success"):
                    return {"success": False, "result": result.get("error", "Message not found"), "error": result.get("error")}
                body_text = result.get("text") or result.get("body") or json.dumps(result, indent=2)
                return {"success": True, "result": body_text, "data": result}

            elif operation == "delete_message":
                inbox_id = input.get("inbox_id", "")
                message_id = input.get("message_id", "")
                result = await agentmail_service.delete_message(inbox_id, message_id)
                return {
                    "success": result["success"],
                    "result": "Message deleted." if result["success"] else result.get("error", "Failed"),
                    "data": result,
                }

            else:
                return {"success": False, "result": f"Unknown operation: {operation}", "error": "Unknown operation"}

        except Exception as exc:
            return {"success": False, "result": str(exc), "error": str(exc)}



class EmailTool(BaseTool):
    name = "email"
    description = (
        "Manage agent email inboxes and send/receive emails. "
        "Use this tool to create inboxes, send emails, read incoming messages, "
        "sign up for platforms using a dedicated agent email address, "
        "and communicate with other agents or users."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "create_inbox",
                    "list_inboxes",
                    "get_inbox",
                    "delete_inbox",
                    "send_email",
                    "list_messages",
                    "get_message",
                    "reply",
                    "delete_message",
                ],
                "description": "Email operation to perform",
            },
            "inbox_id": {
                "type": "string",
                "description": "Inbox ID for inbox-specific operations",
            },
            "username": {
                "type": "string",
                "description": "Desired username for new inbox (e.g. 'myagent' → myagent@agentmail.to). Optional.",
            },
            "display_name": {
                "type": "string",
                "description": "Display name for the inbox (shown as sender name)",
            },
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recipient email addresses for send_email/reply",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Plain-text email body",
            },
            "html": {
                "type": "string",
                "description": "Optional HTML email body (used alongside plain text)",
            },
            "cc": {
                "type": "array",
                "items": {"type": "string"},
                "description": "CC recipients",
            },
            "message_id": {
                "type": "string",
                "description": "Message ID for get_message/reply/delete_message",
            },
            "limit": {
                "type": "integer",
                "description": "Max messages to list (default 20)",
                "default": 20,
            },
        },
        "required": ["operation"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation", "")

        if not agentmail_service.available:
            return ToolResult(
                success=False,
                output="AgentMail is not configured. Please add an AgentMail API key in Settings.",
                error="AgentMail API key not set",
            )

        try:
            if operation == "create_inbox":
                result = await agentmail_service.create_inbox(
                    username=kwargs.get("username"),
                    display_name=kwargs.get("display_name"),
                )
                return ToolResult(
                    success=result["success"],
                    output=f"Created inbox: {result.get('address', result.get('inbox_id', '?'))}",
                    data=result,
                )

            elif operation == "list_inboxes":
                result = await agentmail_service.list_inboxes()
                inboxes = result.get("inboxes", [])
                summary = "\n".join(
                    f"- {i.get('address') or i.get('email', '?')} (id: {i.get('id') or i.get('inbox_id', '?')})"
                    for i in inboxes
                ) or "No inboxes found."
                return ToolResult(success=True, output=summary, data=result)

            elif operation == "get_inbox":
                inbox_id = kwargs.get("inbox_id", "")
                result = await agentmail_service.get_inbox(inbox_id)
                return ToolResult(success=result["success"], output=json.dumps(result, indent=2), data=result)

            elif operation == "delete_inbox":
                inbox_id = kwargs.get("inbox_id", "")
                result = await agentmail_service.delete_inbox(inbox_id)
                return ToolResult(success=result["success"], output="Inbox deleted." if result["success"] else result.get("error", "Failed"), data=result)

            elif operation in ("send_email", "reply"):
                inbox_id = kwargs.get("inbox_id", "")
                to = kwargs.get("to", [])
                subject = kwargs.get("subject", "(no subject)")
                body = kwargs.get("body", "")
                if not inbox_id:
                    return ToolResult(success=False, output="inbox_id is required for send_email", error="Missing inbox_id")
                if not to:
                    return ToolResult(success=False, output="'to' recipients are required", error="Missing to")
                result = await agentmail_service.send_message(
                    inbox_id,
                    to,
                    subject,
                    body,
                    html=kwargs.get("html"),
                    cc=kwargs.get("cc"),
                    reply_to_id=kwargs.get("message_id") if operation == "reply" else None,
                )
                if result["success"]:
                    return ToolResult(
                        success=True,
                        output=f"Email sent to {', '.join(to)} (message_id: {result.get('message_id', '?')})",
                        data=result,
                    )
                return ToolResult(success=False, output=result.get("error", "Send failed"), data=result)

            elif operation == "list_messages":
                inbox_id = kwargs.get("inbox_id", "")
                limit = int(kwargs.get("limit", 20))
                result = await agentmail_service.list_messages(inbox_id, limit=limit)
                messages = result.get("messages", [])
                if not messages:
                    return ToolResult(success=True, output="No messages in inbox.", data=result)
                lines = []
                for m in messages:
                    sender = m.get("from") or m.get("sender", "?")
                    subj = m.get("subject", "(no subject)")
                    date = m.get("date") or m.get("created_at", "")
                    mid = m.get("id") or m.get("message_id", "?")
                    lines.append(f"[{mid}] From: {sender} | {subj} | {date}")
                return ToolResult(success=True, output="\n".join(lines), data=result)

            elif operation == "get_message":
                inbox_id = kwargs.get("inbox_id", "")
                message_id = kwargs.get("message_id", "")
                result = await agentmail_service.get_message(inbox_id, message_id)
                if not result.get("success"):
                    return ToolResult(success=False, output=result.get("error", "Message not found"))
                msg = result
                body_text = msg.get("text") or msg.get("body") or json.dumps(msg, indent=2)
                return ToolResult(success=True, output=body_text, data=result)

            elif operation == "delete_message":
                inbox_id = kwargs.get("inbox_id", "")
                message_id = kwargs.get("message_id", "")
                result = await agentmail_service.delete_message(inbox_id, message_id)
                return ToolResult(success=result["success"], output="Message deleted." if result["success"] else result.get("error", "Failed"), data=result)

            else:
                return ToolResult(success=False, output=f"Unknown operation: {operation}", error="Unknown operation")

        except Exception as exc:
            return ToolResult(success=False, output=str(exc), error=str(exc))
