import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from decisions import canonical_json, decide_packages
from storage import (
    get_message,
    get_task,
    init_db,
    list_tasks_for_principal,
    save_message,
    save_task,
    update_task,
)


app = FastAPI(
    title="Invoice Action Agent",
    version="1.0.0",
)


PROPOSAL_MEDIA_TYPE = (
    "application/vnd.ga5.invoice-action-proposals+json"
)

RESULT_MEDIA_TYPE = (
    "application/vnd.ga5.invoice-action-results+json"
)

RECEIPT_MEDIA_TYPE = (
    "application/vnd.ga5.invoice-action-receipts+json"
)

BATCH_MEDIA_TYPE = (
    "application/vnd.ga5.invoice-claim-batch+json"
)

A2A_MEDIA_TYPE = "application/a2a+json"


@app.on_event("startup")
def startup():
    init_db()


def now():
    return datetime.now(timezone.utc).isoformat()


def get_principal(
    authorization: Optional[str],
):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )

    token = authorization[7:].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )

    return token


def require_headers(
    a2a_version: Optional[str],
    content_type: Optional[str],
):
    if a2a_version != "1.0":
        raise HTTPException(
            status_code=400,
            detail="Invalid A2A version",
        )

    if not content_type:
        raise HTTPException(
            status_code=400,
            detail="Invalid media type",
        )

    media = content_type.split(";")[0].strip()

    if media != A2A_MEDIA_TYPE:
        raise HTTPException(
            status_code=400,
            detail="Invalid media type",
        )


def task_response(task):
    return JSONResponse(
        content={"task": task},
        media_type=A2A_MEDIA_TYPE,
    )


def hash_message(message):
    return hashlib.sha256(
        canonical_json(message).encode("utf-8")
    ).hexdigest()


def find_proposals(task):
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            if (
                part.get("mediaType")
                == PROPOSAL_MEDIA_TYPE
            ):
                return part.get("data")

    return None


def validate_initial_message(message):
    if message.get("role") != "ROLE_USER":
        raise HTTPException(
            status_code=400,
            detail="Invalid message",
        )

    parts = message.get("parts")

    if not isinstance(parts, list):
        raise HTTPException(
            status_code=400,
            detail="Missing invoice batch",
        )

    batch_part = None

    for part in parts:
        if part.get("mediaType") == BATCH_MEDIA_TYPE:
            batch_part = part
            break

    if batch_part is None:
        raise HTTPException(
            status_code=400,
            detail="Missing invoice batch",
        )

    data = batch_part.get("data")

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid invoice batch",
        )

    batch_id = data.get("batchId")
    policy_revision = data.get("policyRevision")
    packages = data.get("packages")

    if not batch_id or not policy_revision:
        raise HTTPException(
            status_code=400,
            detail="Invalid invoice batch",
        )

    if not isinstance(packages, list) or not packages:
        raise HTTPException(
            status_code=400,
            detail="Invalid invoice packages",
        )

    package_ids = [
        package.get("packageId")
        for package in packages
    ]

    if (
        any(not package_id for package_id in package_ids)
        or len(package_ids) != len(set(package_ids))
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid package IDs",
        )

    return data


def build_proposals(
    packages,
):
    decisions = decide_packages(packages)

    proposals = []

    for decision in decisions:
        proposals.append(
            {
                "packageId": decision["packageId"],
                "actionId": str(uuid.uuid4()),
                "action": decision["action"],
                "facts": decision["facts"],
                "evidenceRefs": decision["evidenceRefs"],
                "rationale": decision["rationale"],
            }
        )

    return proposals


def append_history(task, message):
    task.setdefault("history", [])
    task["history"].append(message)


@app.get("/.well-known/agent-card.json")
def agent_card(
    request: Request,
):
    base_url = os.environ.get(
        "A2A_BASE_URL"
    )

    if not base_url:
        base_url = (
            str(request.base_url).rstrip("/")
            + "/a2a/"
        )

    return JSONResponse(
        content={
            "name": "Invoice Action Agent",
            "description": (
                "An evidence-based invoice action agent."
            ),
            "version": "1.0.0",
            "capabilities": {},
            "skills": [
                {
                    "name": "invoice_action_agent",
                    "description": (
                        "Analyse invoice packages and "
                        "propose safe business actions."
                    ),
                    "tags": [
                        "invoice",
                        "payment",
                        "evidence",
                    ],
                }
            ],
            "supportedInterfaces": [
                {
                    "url": base_url,
                    "protocolBinding": "HTTP+JSON",
                    "protocolVersion": "1.0",
                }
            ],
            "defaultInputModes": [
                BATCH_MEDIA_TYPE
            ],
            "defaultOutputModes": [
                PROPOSAL_MEDIA_TYPE,
                RECEIPT_MEDIA_TYPE,
            ],
        }
    )


@app.post("/a2a/message:send")
async def send_message(
    request: Request,
    authorization: Optional[str] = Header(
        default=None
    ),
    a2a_version: Optional[str] = Header(
        default=None,
        alias="A2A-Version",
    ),
    content_type: Optional[str] = Header(
        default=None,
        alias="Content-Type",
    ),
):
    principal = get_principal(
        authorization
    )

    require_headers(
        a2a_version,
        content_type,
    )

    body = await request.json()

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid request",
        )

    message = body.get("message")

    if not isinstance(message, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid message",
        )

    message_id = message.get("messageId")

    if not message_id:
        raise HTTPException(
            status_code=400,
            detail="Missing message ID",
        )

    incoming_hash = hash_message(message)

    # --------------------------------------------------
    # MESSAGE IDEMPOTENCY
    # --------------------------------------------------

    existing_message = get_message(
        principal,
        message_id,
    )

    if existing_message:
        if (
            existing_message["message_hash"]
            != incoming_hash
        ):
            raise HTTPException(
                status_code=409,
                detail="IDEMPOTENCY_CONFLICT",
            )

        existing_task = get_task(
            existing_message["task_id"],
            principal,
        )

        if existing_task is None:
            raise HTTPException(
                status_code=500,
                detail="Stored task unavailable",
            )

        return task_response(existing_task)

    # --------------------------------------------------
    # RESULT CONTINUATION
    # --------------------------------------------------

    if message.get("taskId"):
        task_id = message.get("taskId")
        context_id = message.get("contextId")

        task = get_task(
            task_id,
            principal,
        )

        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )

        if task.get("contextId") != context_id:
            raise HTTPException(
                status_code=400,
                detail="Invalid task context",
            )

        # Terminal task + new message cannot mutate it.
        if task["status"]["state"] in {
            "TASK_STATE_COMPLETED",
            "TASK_STATE_CANCELED",
        }:
            raise HTTPException(
                status_code=409,
                detail="Task already terminal",
            )

        result_part = None

        for part in message.get("parts", []):
            if (
                part.get("mediaType")
                == RESULT_MEDIA_TYPE
            ):
                result_part = part
                break

        if result_part is None:
            raise HTTPException(
                status_code=400,
                detail="Missing action results",
            )

        result_data = result_part.get("data")

        if not isinstance(result_data, dict):
            raise HTTPException(
                status_code=400,
                detail="Invalid action results",
            )

        batch_id = result_data.get("batchId")
        results = result_data.get("results")

        proposal_data = find_proposals(task)

        if proposal_data is None:
            raise HTTPException(
                status_code=400,
                detail="Missing stored proposals",
            )

        if batch_id != proposal_data.get("batchId"):
            raise HTTPException(
                status_code=400,
                detail="Invalid batch",
            )

        if not isinstance(results, list):
            raise HTTPException(
                status_code=400,
                detail="Invalid action results",
            )

        stored_proposals = {
            p["packageId"]: p
            for p in proposal_data.get(
                "proposals",
                [],
            )
        }

        executions = []

        for result in results:
            package_id = result.get(
                "packageId"
            )
            action_id = result.get(
                "actionId"
            )
            action = result.get(
                "action"
            )
            outcome = result.get(
                "outcome"
            )
            receipt_nonce = result.get(
                "receiptNonce"
            )

            proposal = stored_proposals.get(
                package_id
            )

            if proposal is None:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid proposal",
                )

            if proposal["actionId"] != action_id:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid action ID",
                )

            if proposal["action"] != action:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid action",
                )

            if outcome not in {
                "ACCEPTED",
                "REJECTED",
            }:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid outcome",
                )

            if outcome == "ACCEPTED":
                if not receipt_nonce:
                    raise HTTPException(
                        status_code=400,
                        detail="Missing receipt nonce",
                    )

                executions.append(
                    {
                        "packageId": package_id,
                        "actionId": action_id,
                        "action": action,
                        "receiptNonce": receipt_nonce,
                        "facts": proposal["facts"],
                        "evidenceRefs": proposal[
                            "evidenceRefs"
                        ],
                    }
                )

        # Persist continuation before returning.
        append_history(
            task,
            message,
        )

        task["artifacts"].append(
            {
                "parts": [
                    {
                        "mediaType": RECEIPT_MEDIA_TYPE,
                        "data": {
                            "batchId": batch_id,
                            "executions": executions,
                        },
                    }
                ]
            }
        )

        task["status"]["state"] = (
            "TASK_STATE_COMPLETED"
        )

        updated = update_task(
            task,
            principal,
        )

        if not updated:
            raise HTTPException(
                status_code=409,
                detail="Task already terminal",
            )

        try:
            save_message(
                principal,
                message_id,
                incoming_hash,
                task_id,
            )
        except Exception:
            # The Task has already become terminal.
            # A retry with the same message is recovered
            # through the stored Task.
            pass

        return task_response(task)

    # --------------------------------------------------
    # INITIAL MESSAGE
    # --------------------------------------------------

    batch = validate_initial_message(
        message
    )

    packages = batch["packages"]

    try:
        proposals = build_proposals(
            packages
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Invoice decision failed",
        ) from exc

    task_id = str(uuid.uuid4())
    context_id = str(uuid.uuid4())

    task = {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": "TASK_STATE_INPUT_REQUIRED"
        },
        "history": [
            message
        ],
        "artifacts": [
            {
                "parts": [
                    {
                        "mediaType": (
                            PROPOSAL_MEDIA_TYPE
                        ),
                        "data": {
                            "batchId": batch[
                                "batchId"
                            ],
                            "proposals": proposals,
                        },
                    }
                ]
            }
        ],
    }

    # Store Task first.
    save_task(
        task,
        principal,
    )

    # Then reserve message ID.
    try:
        save_message(
            principal,
            message_id,
            incoming_hash,
            task_id,
        )
    except Exception:
        # Concurrent equivalent request won.
        existing = get_message(
            principal,
            message_id,
        )

        if existing:
            existing_task = get_task(
                existing["task_id"],
                principal,
            )

            if existing_task:
                return task_response(
                    existing_task
                )

        raise HTTPException(
            status_code=409,
            detail="IDEMPOTENCY_CONFLICT",
        )

    return task_response(task)


@app.get("/a2a/tasks/{task_id}")
def read_task(
    task_id: str,
    authorization: Optional[str] = Header(
        default=None
    ),
):
    principal = get_principal(
        authorization
    )

    task = get_task(
        task_id,
        principal,
    )

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return JSONResponse(
        content=task,
        media_type=A2A_MEDIA_TYPE,
    )


@app.get("/a2a/tasks")
def list_tasks(
    authorization: Optional[str] = Header(
        default=None
    ),
):
    principal = get_principal(
        authorization
    )

    tasks = list_tasks_for_principal(
        principal
    )

    return JSONResponse(
        content={"tasks": tasks},
        media_type=A2A_MEDIA_TYPE,
    )


@app.post("/a2a/tasks/{task_id}:cancel")
def cancel_task(
    task_id: str,
    authorization: Optional[str] = Header(
        default=None
    ),
):
    principal = get_principal(
        authorization
    )

    task = get_task(
        task_id,
        principal,
    )

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    if task["status"]["state"] in {
        "TASK_STATE_COMPLETED",
        "TASK_STATE_CANCELED",
    }:
        raise HTTPException(
            status_code=409,
            detail="Task already terminal",
        )

    task["status"]["state"] = (
        "TASK_STATE_CANCELED"
    )

    updated = update_task(
        task,
        principal,
    )

    if not updated:
        raise HTTPException(
            status_code=409,
            detail="Task already terminal",
        )

    return JSONResponse(
        content=task,
        media_type=A2A_MEDIA_TYPE,
    )