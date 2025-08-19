import os, json, time, logging, boto3
from datetime import datetime, timedelta, timezone

import mysql.connector
from mysql.connector import pooling, Error as MySQLError

from app.auth import verify_google_token
from app.tools import add_goal
from app.llm_flow import run_goal_planner

log = logging.getLogger()
log.setLevel(logging.INFO)

# ── DB config (use your RDS Proxy endpoint for DB_HOST) ───────────────────
DB_CFG = {
    "host":     os.environ["DB_HOST"],
    "user":     os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
    "port":     int(os.environ.get("DB_PORT", "3306")),
    "connection_timeout": 5,
}

# Global pool reused across warm invocations
POOL = None

def get_conn():
    global POOL
    if POOL is None:
        # Small pool is fine for Lambda; scale if you raise provisioned concurrency
        POOL = pooling.MySQLConnectionPool(pool_name="ws-pool", pool_size=4, **DB_CFG)
    try:
        cnx = POOL.get_connection()
        cnx.ping(reconnect=True, attempts=1, delay=0)  # ensure alive
        return cnx
    except MySQLError:
        # Rebuild pool on error (rare)
        POOL = pooling.MySQLConnectionPool(pool_name="ws-pool", pool_size=4, **DB_CFG)
        return POOL.get_connection()

def map_connection(user_id: str, conn_id: str, hours=3):
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as cnx, cnx.cursor(dictionary=True) as cur:
        cur.execute(
            """
            INSERT INTO ws_connections (connection_id, user_id, expires_at)
            VALUES (%s,%s,%s)
            ON DUPLICATE KEY UPDATE user_id=VALUES(user_id), expires_at=VALUES(expires_at)
            """,
            (conn_id, user_id, expires_at)
        )
        cnx.commit()

def get_user_by_connection(conn_id: str):
    with get_conn() as cnx, cnx.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT user_id
              FROM ws_connections
             WHERE connection_id=%s
               AND (expires_at IS NULL OR expires_at > UTC_TIMESTAMP())
            """,
            (conn_id,)
        )
        row = cur.fetchone()
        return row["user_id"] if row else None

def delete_connection(conn_id: str):
    with get_conn() as cnx, cnx.cursor() as cur:
        cur.execute("DELETE FROM ws_connections WHERE connection_id=%s", (conn_id,))
        cnx.commit()

def cleanup_expired(limit=200):
    with get_conn() as cnx, cnx.cursor() as cur:
        cur.execute("DELETE FROM ws_connections WHERE expires_at < UTC_TIMESTAMP() LIMIT %s", (limit,))
        cnx.commit()

# ── API Gateway mgmt client (for post_to_connection) ───────────────────────
def mgmt_client(event):
    rc = event["requestContext"]
    return boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=f"https://{rc['domainName']}/{rc['stage']}"
    )

def reply(event, payload):
    mgmt_client(event).post_to_connection(
        ConnectionId=event["requestContext"]["connectionId"],
        Data=json.dumps(payload).encode("utf-8")
    )

# ── Routes ─────────────────────────────────────────────────────────────────
def on_connect(event):
    # Optionally verify a token in query string to gate connects.
    return {"statusCode": 200}

def on_disconnect(event):
    try:
        delete_connection(event["requestContext"]["connectionId"])
    except Exception as e:
        log.warning(f"disconnect cleanup error: {e}")
    return {"statusCode": 200}

def on_message(event):
    cleanup_expired()
    body = json.loads(event.get("body") or "{}")
    msg_type = body.get("type")
    args = body.get("args", {}) or {}

    if msg_type == "auth":
        token = args.get("token")
        if not token:
            reply(event, {"type":"auth_response","data":{"status":"error","message":"Token required"}})
            return {"statusCode": 200}
        user_info = verify_google_token(token, os.environ["GOOGLE_CLIENT_ID"])
        if not user_info:
            reply(event, {"type":"auth_response","data":{"status":"error","message":"Invalid token"}})
            return {"statusCode": 200}
        user_id = user_info["sub"]
        map_connection(user_id, event["requestContext"]["connectionId"], hours=3)
        reply(event, {"type":"auth_response","data":{"status":"success","user_id":user_id,"user_info":user_info}})
        return {"statusCode": 200}

    def resolve_user():
        uid = args.get("user")
        return uid or get_user_by_connection(event["requestContext"]["connectionId"])

    if msg_type == "add_goal":
        user_id = resolve_user()
        if not user_id:
            reply(event, {"type":"add_goal_response","data":{"status":"error","message":"Not authenticated"}})
            return {"statusCode": 200}

        title       = args.get("title")
        category    = args.get("category")
        description = args.get("description")
        deadline    = args.get("deadline")
        email_updates = args.get("emailUpdates", "never")
        milestones  = args.get("milestones", [])

        if isinstance(email_updates, list):
            email_updates = ("daily" if "daily" in email_updates else
                             "weekly" if "weekly" in email_updates else
                             "monthly" if "monthly" in email_updates else "never")
        elif not isinstance(email_updates, str):
            email_updates = "never"

        if not all([title, category, description, deadline]):
            reply(event, {"type":"add_goal_response","data":{"status":"error","message":"Missing required fields"}})
            return {"statusCode": 200}

        try:
            result = add_goal.invoke({
                "title": title, "category": category, "description": description,
                "deadline": deadline, "user_id": user_id,
                "milestones": milestones, "email_updates": email_updates
            })
            result_data = json.loads(result) if isinstance(result, str) else (result or {})
            reply(event, {"type":"add_goal_response","data":{
                "status":"success",
                "goal": result_data.get("goal", {}),
                "title": title, "category": category,
                "description": description, "deadline": deadline,
                "emailUpdates": email_updates,
                "routine": result_data.get("goal", {}).get("routine", [])
            }})
        except Exception as e:
            log.exception("add_goal failed")
            reply(event, {"type":"add_goal_response","data":{"status":"error","message": f"Failed to add goal: {e}"}})
        return {"statusCode": 200}

    if msg_type == "chat":
        user_id = resolve_user()
        if not user_id or not args.get("message"):
            reply(event, {"type":"chat_response","data":{"status":"error","message":"User ID and message are required"}})
            return {"statusCode": 200}
        try:
            result = run_goal_planner(user_id, args["message"])
            reply(event, {"type":"chat_response","data":{"status":"success","result": result}})
        except Exception as e:
            log.exception("chat error")
            reply(event, {"type":"chat_response","data":{"status":"error","message": str(e)}})
        return {"statusCode": 200}

    reply(event, {"type":"error","data":{"message": f"Unknown type: {msg_type}"}})
    return {"statusCode": 200}

def handler(event, context):
    route = event["requestContext"]["routeKey"]
    if route == "$connect":    return on_connect(event)
    if route == "$disconnect": return on_disconnect(event)
    return on_message(event)
