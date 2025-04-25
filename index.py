from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, close_room
from dotenv import load_dotenv
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from mysql.connector import pooling
import os
import json
import logging


# Configure logging
logging.basicConfig(
    filename="services_info.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)
CORS(app)

load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')

socketio = SocketIO(app, cors_allowed_origins="*")
logging.info("Flask SocketIO server starting...")

# --- MySQL Connector Pool Setup ---
db_config = {
    'host': os.getenv("DB_HOST", "localhost"),
    'user': os.getenv("DB_USER", "root"),
    'password': os.getenv("DB_PASSWORD", ""),
    'database': os.getenv("DB_NAME", "chat_db")
}

# Create a connection pool. Adjust pool_size as needed.
try:
    cnxpool = pooling.MySQLConnectionPool(
        pool_name="mypool", pool_size=5, **db_config)
    logging.info("MySQL connection pool created successfully.")
except Exception as e:
    logging.error("Error creating MySQL connection pool", exc_info=True)
    raise


@contextmanager
def get_db_cursor():
    """
    Context manager that yields a connection and cursor.
    Commits changes if no exception occurred; otherwise rolls back.
    Ensures that connection is returned to the pool.
    """
    connection = cnxpool.get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        yield connection, cursor
    except Exception as e:
        connection.rollback()
        raise e
    else:
        connection.commit()
    finally:
        cursor.close()
        connection.close()


# --- Create necessary tables if they do not exist ---
with get_db_cursor() as (conn, cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id INT AUTO_INCREMENT PRIMARY KEY,
            tenant_name VARCHAR(255) UNIQUE,
            tenant_url TEXT,
            created_at DATETIME,
            updated_at DATETIME,
            created_by VARCHAR(255),
            updated_by VARCHAR(255),
            apiKey TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_connection_id VARCHAR(255) UNIQUE,
            agent_name VARCHAR(255),
            domain VARCHAR(255),
            status VARCHAR(50),
            tenant_id INT,
            user_count INT DEFAULT 0,
            last_update DATETIME,
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_connection_id VARCHAR(255) UNIQUE,
            user_name VARCHAR(255), 
            user_id VARCHAR(255),  
            agent_connection_id VARCHAR(255),
            tenant_id INT,
            connection_time DATETIME,
            disconnection_time DATETIME,
            FOREIGN KEY (agent_connection_id) REFERENCES agents(agent_connection_id),
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id INT AUTO_INCREMENT PRIMARY KEY,
            user_connection_id VARCHAR(255) UNIQUE,
            agent_connection_id VARCHAR(255),
            user_name VARCHAR(255),         
            messages JSON,
            last_update DATETIME,
            tenant_id INT,
            status BOOLEAN,
            FOREIGN KEY (agent_connection_id) REFERENCES agents(agent_connection_id),
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
            FOREIGN KEY (user_connection_id) REFERENCES users(user_connection_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INT AUTO_INCREMENT PRIMARY KEY,
            subject VARCHAR(255),
            message TEXT,
            rating INT,
            image_url TEXT,
            addedAt DATETIME,
            updatedAt DATETIME,
            status VARCHAR(50),
            addedBy VARCHAR(255),
            updatedBy VARCHAR(255),
            tenant_id INT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
            FOREIGN KEY (addedBy) REFERENCES users(user_connection_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS querys  (
            id INT AUTO_INCREMENT PRIMARY KEY,
            emailId VARCHAR(50),
            userName VARCHAR(50),
            message VARCHAR(250),
            domain VARCHAR(255),
            resolvedBy VARCHAR(255),
            updatedAt DATETIME,
            status VARCHAR(50),
            tenant_id INT,
            agent_id VARCHAR(255),
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
            FOREIGN KEY (agent_id) REFERENCES agents(agent_connection_id)
        )
    """)

# Maximum users allowed per agent
MAX_USERS_PER_AGENT = 2

# --- In-memory Structures ---
# {agent_connection_id: {"status": "online", "domain": "...", "agent_name": "..."}}
agents = {}
# Mapping: user_connection_id -> agent_connection_id (and vice versa)
users_mapping = {}
agent_queues = {}   # {domain: deque([agent1, agent2, ...])}


@socketio.on('register_agent')
def register_agent(data):
    domain = data.get('domain')
    old_agent_id = data.get('old_agent_id')
    agent_name = data.get('agent_name')
    if not domain:
        emit('error', {
             'message': 'Domain is required to register as an agent'}, room=request.sid)
        return

    agent_connection_id = old_agent_id if old_agent_id is not None else request.sid
    timestamp = datetime.now()
    join_room(agent_connection_id)

    try:
        with get_db_cursor() as (conn, cursor):
            cursor.execute(
                "SELECT agent_connection_id FROM agents WHERE agent_connection_id = %s",
                (agent_connection_id,)
            )
            existing_agent = cursor.fetchone()

            if existing_agent:
                # Remove from old queue if domain changed
                old_domain = agents.get(agent_connection_id, {}).get("domain")
                if old_domain and old_domain != domain and old_domain in agent_queues:
                    try:
                        agent_queues[old_domain].remove(agent_connection_id)
                    except ValueError:
                        pass

                # Update status, domain, name, timestamp
                cursor.execute("""
                    UPDATE agents
                       SET status       = %s,
                           last_update  = %s,
                           domain       = %s,
                           agent_name   = %s
                     WHERE agent_connection_id = %s
                """, ("online", timestamp, domain, agent_name, agent_connection_id))

                agents[agent_connection_id] = {
                    "status": "online",
                    "domain": domain,
                    "agent_name": agent_name
                }
                agent_queues.setdefault(
                    domain, deque()).append(agent_connection_id)

                emit('agent_status', {
                     'agent_connection_id': agent_connection_id, 'status': 'online'}, broadcast=True)
                logging.info(
                    f'Agent {agent_connection_id} reconnected in domain {domain}.')
                return {'agent_connection_id': agent_connection_id}

            # New agent
            agents[agent_connection_id] = {
                "status": "online", "domain": domain, "agent_name": agent_name}
            agent_queues.setdefault(
                domain, deque()).append(agent_connection_id)

            cursor.execute("""
                INSERT INTO agents (agent_connection_id, agent_name, domain, status, last_update)
                VALUES (%s, %s, %s, %s, %s)
            """, (agent_connection_id, agent_name, domain, "online", timestamp))

            emit('agent_status', {
                 'agent_connection_id': agent_connection_id, 'status': 'online'}, broadcast=True)
            logging.info(
                f'New agent {agent_connection_id} registered in domain {domain}.')
            return {'agent_connection_id': agent_connection_id}

    except Exception as e:
        logging.error("Error in register_agent", exc_info=True)
        emit('error', {
             'message': 'Failed to register agent due to a database error.'}, room=request.sid)


@socketio.on('agent_offline')
def handle_agent_offline(data):
    agent_id = data.get('agent_connection_id')
    timestamp = datetime.now()

    # 1. Update MySQL
    try:
        with get_db_cursor() as (conn, cursor):
            cursor.execute(
                "UPDATE agents SET status = %s, last_update = %s WHERE agent_connection_id = %s",
                ("offline", timestamp, agent_id)
            )
    except Exception as e:
        logging.error("Error setting agent offline", exc_info=True)

    # 2. Remove from in‑memory state
    domain = agents.get(agent_id, {}).get("domain")
    agents.pop(agent_id, None)
    if domain and agent_id in agent_queues.get(domain, []):
        agent_queues[domain].remove(agent_id)

    # 3. Broadcast the status change
    emit('agent_status', {
        'agent_connection_id': agent_id,
        'status': 'offline'
    }, broadcast=True)


@socketio.on('request_live_chat')
def request_live_chat(data):
    """
    Assigns or restores a live chat for a user using a round-robin method
    with a maximum user capacity per agent.
    """
    domain = data.get('domain')
    user_connection_id = data.get('old_user_id') or request.sid
    user_id = data.get('user_id')
    user_name = data.get('user_name')

    if not domain:
        emit('no_agents_available', {
             'message': 'Domain is required'}, room=user_connection_id)
        logging.info(
            f"User {user_connection_id} requested chat with no domain provided.")
        return

    join_room(user_connection_id)
    timestamp = datetime.now()

    try:
        with get_db_cursor() as (conn, cursor):
            # Check if user already exists with an active conversation.
            cursor.execute(
                "SELECT * FROM users WHERE user_connection_id = %s", (user_connection_id,))
            existing_user = cursor.fetchone()
            if existing_user:
                cursor.execute(
                    "SELECT * FROM conversations WHERE user_connection_id = %s AND status = TRUE", (user_connection_id,))
                conversation = cursor.fetchone()
                if conversation:
                    try:
                        messages = json.loads(conversation['messages'])
                    except Exception as e:
                        logging.error(
                            f"Failed to load messages for user {user_connection_id}: {e}")
                        messages = []
                    cursor.execute("""
                        UPDATE users SET connection_time = %s, disconnection_time = NULL WHERE user_connection_id = %s
                    """, (timestamp, user_connection_id))
                    users_mapping[user_connection_id] = conversation['agent_connection_id']
                    users_mapping.setdefault(
                        conversation['agent_connection_id'], []).append(user_connection_id)
                    emit('live_chat_reconnected', {
                        'agent_connection_id': conversation['agent_connection_id'],
                        'agent_name': agents.get(conversation['agent_connection_id'], {}).get('agent_name', 'Agent'),
                        'user_connection_id': user_connection_id,
                        'messages': messages
                    }, room=user_connection_id)
                    emit('user_reconnected', {'user_connection_id': user_connection_id, 'user_name': user_name},
                         room=conversation['agent_connection_id'])
                    logging.info(
                        f"Reconnected chat for user {user_connection_id} with agent {conversation['agent_connection_id']}.")
                    return {'user_connection_id': user_connection_id}

            # --- Agent Assignment using Round-Robin with Capacity Check ---
            cursor.execute(
                "SELECT agent_connection_id, user_count FROM agents WHERE domain = %s AND status = 'online'", (domain,))
            available_agents = cursor.fetchall()

            if not available_agents:
                emit('no_agents_available', {
                     'message': 'No agents available'}, room=user_connection_id)
                logging.info(f"No agents online for domain {domain}.")
                return

            # Filter agents that are under capacity.
            available_agents = [
                agent for agent in available_agents if agent['user_count'] < MAX_USERS_PER_AGENT]

            if not available_agents:
                emit('no_agents_available', {
                     'message': 'All agents are currently busy. Please try again later.'}, room=user_connection_id)
                logging.info(
                    f"All agents in domain {domain} are at maximum capacity.")
                return

            # Sort available agents by user_count and pick the one with the least users.
            available_agents.sort(key=lambda agent: agent['user_count'])
            assigned_agent = available_agents[0]['agent_connection_id']

            # Increment the agent's user_count.
            cursor.execute("UPDATE agents SET user_count = user_count + 1, last_update = %s WHERE agent_connection_id = %s",
                           (timestamp, assigned_agent))

            # Map the user to the assigned agent.
            users_mapping[user_connection_id] = assigned_agent
            users_mapping.setdefault(
                assigned_agent, []).append(user_connection_id)

            # Insert a record for the user.
            cursor.execute("""
                INSERT INTO users (user_connection_id, user_id, user_name, agent_connection_id, connection_time)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_connection_id, user_id, user_name, assigned_agent, timestamp))

            # Create a new conversation record with empty messages.
            messages_list = []
            messages_json = json.dumps(messages_list)
            cursor.execute("""
                INSERT INTO conversations (user_connection_id, agent_connection_id, user_name, messages, last_update, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_connection_id, assigned_agent, user_name, messages_json, timestamp, True))

            emit('live_chat_connected', {
                'agent_connection_id': assigned_agent,
                'agent_name': agents.get(assigned_agent, {}).get('agent_name', 'Agent'),
                'user_connection_id': user_connection_id,
                'messages': []
            }, room=user_connection_id)
            emit('new_live_chat', {
                 'user_connection_id': user_connection_id, 'user_name': user_name}, room=assigned_agent)
            logging.info(
                f"New user {user_connection_id} connected to agent {assigned_agent} in domain {domain}.")
            return {'user_connection_id': user_connection_id, 'agent_connection_id': assigned_agent}
    except Exception as e:
        logging.error("Error in request_live_chat", exc_info=True)
        emit('error', {
             'message': 'Failed to assign live chat due to a database error.'}, room=user_connection_id)


@socketio.on('restore_chats')
def restore_chats(data):
    """
    Restores all active chats for an agent upon reconnection.
    """
    agent_connection_id = data.get('agent_connection_id')
    if not agent_connection_id:
        return

    try:
        with get_db_cursor() as (conn, cursor):
            cursor.execute("""
                SELECT user_connection_id, messages, user_name
                FROM conversations 
                WHERE agent_connection_id = %s AND status = %s
            """, (agent_connection_id, True))
            active_convos = cursor.fetchall()
            restored_chats = {}
            for convo in active_convos:
                try:
                    messages = json.loads(convo['messages'])
                except Exception as e:
                    logging.error(
                        f"Error loading messages for {convo['user_connection_id']}: {e}")
                    messages = []
                restored_chats[convo['user_connection_id']] = {
                    "messages": messages,
                    "userName": convo["user_name"] or f"User {convo['user_connection_id']}"
                }
            emit('restore_active_chats', restored_chats)
    except Exception as e:
        logging.error("Error in restore_chats", exc_info=True)


@socketio.on('send_message')
def send_message(data):
    """
    Receives a message from either user or agent.
    The client sends 'persistent_id' (stored ID) along with the message.
    """
    persistent_sender = data.get('persistent_id', request.sid)
    recipient_id = data.get('recipient_id')
    message_text = data.get('message', '').strip()
    image = data.get('image', None)
    timestamp = datetime.now()

    if not recipient_id:
        logging.warning(f"Message from {persistent_sender} has no recipient.")
        return

    role = "agent" if persistent_sender in agents else "user"

    new_message = {
        "timestamp": timestamp.isoformat(),
        "sender": role,
        "message": message_text,
        "image": image
    }

    # For user messages, the conversation key is the user_connection_id;
    # For agent messages, the recipient is the user.
    conversation_key = persistent_sender if role == "user" else recipient_id

    try:
        with get_db_cursor() as (conn, cursor):
            # Ensure user exists in the users table.
            cursor.execute(
                "SELECT user_connection_id FROM users WHERE user_connection_id = %s", (conversation_key,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO users (user_connection_id, agent_connection_id, connection_time)
                    VALUES (%s, %s, %s)
                """, (conversation_key, persistent_sender if role == "user" else None, timestamp))

            cursor.execute(
                "SELECT messages FROM conversations WHERE user_connection_id = %s", (conversation_key,))
            result = cursor.fetchone()

            if result:
                try:
                    messages_list = json.loads(result['messages'])
                except Exception as e:
                    logging.error(
                        f"Error decoding JSON for {conversation_key}: {e}")
                    messages_list = []
                messages_list.append(new_message)
                updated_messages = json.dumps(messages_list)
                if role == "agent":
                    cursor.execute("""
                        UPDATE conversations 
                        SET messages = %s, last_update = %s, agent_connection_id = %s, status = %s
                        WHERE user_connection_id = %s
                    """, (updated_messages, timestamp, persistent_sender, True, conversation_key))
                else:
                    cursor.execute("""
                        UPDATE conversations 
                        SET messages = %s, last_update = %s
                        WHERE user_connection_id = %s
                    """, (updated_messages, timestamp, conversation_key))
            else:
                messages_list = [new_message]
                messages_json = json.dumps(messages_list)
                if role == "agent":
                    cursor.execute("""
                        INSERT INTO conversations (user_connection_id, agent_connection_id, messages, last_update, status)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (conversation_key, persistent_sender, messages_json, timestamp, True))
                else:
                    cursor.execute("""
                        INSERT INTO conversations (user_connection_id, messages, last_update)
                        VALUES (%s, %s, %s)
                    """, (conversation_key, messages_json, timestamp))
    except Exception as e:
        logging.error("Database error in send_message", exc_info=True)
        emit('error', {
             'message': 'Failed to send message due to a database error.'}, room=persistent_sender)
        return

    emit('receive_message', {'from': persistent_sender,
         'message': message_text, 'image': image}, room=recipient_id)
    logging.info(
        f"Message from {persistent_sender} to {recipient_id} logged and forwarded.")


@socketio.on('end_chat')
def end_chat(data):
    """
    Ends a live chat and updates the conversation's status.
    Also decrements the agent's user_count accordingly.
    """
    user_connection_id = data.get('user_connection_id')
    agent_connection_id = users_mapping.get(user_connection_id)
    logging.info(
        f"Chat ended by user {user_connection_id} with agent {agent_connection_id}")
    if agent_connection_id:
        timestamp = datetime.now()
        try:
            with get_db_cursor() as (conn, cursor):
                cursor.execute("""
                    UPDATE conversations 
                    SET status = FALSE, last_update = %s
                    WHERE user_connection_id = %s
                """, (timestamp, user_connection_id))
                cursor.execute("""
                    UPDATE users 
                    SET disconnection_time = %s
                    WHERE user_connection_id = %s
                """, (timestamp, user_connection_id))
                cursor.execute("""
                    UPDATE agents 
                    SET user_count = GREATEST(0, user_count - 1), last_update = %s
                    WHERE agent_connection_id = %s
                """, (timestamp, agent_connection_id))
            emit('chat_ended', {
                 'partner_id': user_connection_id}, room=agent_connection_id)
            emit('chat_ended', {
                 'partner_id': agent_connection_id}, room=user_connection_id)
            if user_connection_id in users_mapping:
                del users_mapping[user_connection_id]
            if agent_connection_id in users_mapping and isinstance(users_mapping[agent_connection_id], list):
                if user_connection_id in users_mapping[agent_connection_id]:
                    users_mapping[agent_connection_id].remove(
                        user_connection_id)
            logging.info(
                f"Chat ended by user {user_connection_id} with agent {agent_connection_id}")
        except Exception as e:
            logging.error("Error ending chat", exc_info=True)


@socketio.on('disconnect')
def handle_disconnect(reason=None):
    """
    Handles disconnects for agents and users.
    """
    sid = request.sid
    timestamp = datetime.now()
    if sid in agents:
        domain = agents[sid]["domain"]
        del agents[sid]
        if domain in agent_queues and sid in agent_queues[domain]:
            agent_queues[domain].remove(sid)
        try:
            with get_db_cursor() as (conn, cursor):
                cursor.execute("UPDATE agents SET status = %s, last_update = %s WHERE agent_connection_id = %s",
                               ("offline", timestamp, sid))
            emit('agent_status', {'agent_connection_id': sid,
                 'status': 'offline'}, broadcast=True)
        except Exception as e:
            logging.error("Error during agent disconnect", exc_info=True)
        logging.info(
            f'Agent {sid} (Domain: {domain}) went offline. Reason: {reason}')
    partner_id = users_mapping.pop(sid, None)
    if partner_id:
        try:
            with get_db_cursor() as (conn, cursor):
                cursor.execute("UPDATE users SET disconnection_time = %s WHERE user_connection_id = %s",
                               (timestamp, sid))
        except Exception as e:
            logging.error("Error updating user disconnect", exc_info=True)
        if partner_id in users_mapping and isinstance(users_mapping[partner_id], list):
            if sid in users_mapping[partner_id]:
                users_mapping[partner_id].remove(sid)
        emit('chat_ended', {'partner_id': sid}, room=partner_id)
        logging.info(
            f"Chat ended between {sid} and {partner_id}. Reason: {reason}")
    close_room(sid)

# --- Query Endpoints ---


@app.route('/previous_chats', methods=['GET'])
def previous_chats():
    agent_id = request.args.get('agent_id')
    page = max(int(request.args.get('page', 1)), 1)
    per_page = min(int(request.args.get('per_page', 10)), 100)

    if not agent_id:
        return jsonify(error="Missing agent_id"), 400

    offset = (page - 1) * per_page

    try:
        with get_db_cursor() as (conn, cursor):
            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM conversations
                WHERE agent_connection_id = %s AND status = FALSE
            """, (agent_id,))
            total = cursor.fetchone()['cnt']

            cursor.execute("""
                SELECT user_connection_id, messages, user_name
                FROM conversations
                WHERE agent_connection_id = %s AND status = FALSE
                ORDER BY last_update DESC
                LIMIT %s OFFSET %s
            """, (agent_id, per_page, offset))
            rows = cursor.fetchall()

        chats = {}
        for row in rows:
            try:
                msgs = json.loads(row['messages'])
            except:
                msgs = []
            chats[row['user_connection_id']] = {
                "messages": msgs,
                "userName": row['user_name'] or f"User {row['user_connection_id']}"
            }

        return jsonify({
            "chats":     chats,
            "page":      page,
            "per_page":  per_page,
            "total":     total,
            "has_more":  offset + len(rows) < total
        })

    except Exception:
        logging.exception("Error in /api/previous_chats")
        return jsonify(error="Server error"), 500


@app.route('/queries', methods=['GET'])
def get_queries():
    # Pagination parameters
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        abort(400, 'Invalid pagination parameters')
    offset = (page - 1) * per_page

    status = request.args.get('status')
    if not status:
        abort(400, 'status is required')

    domain = request.args.get('domain', '').strip()

    with get_db_cursor() as (conn, cursor):
        total_count = 0
        queries = []

        if domain:
            # Get total count
            cursor.execute(
                "SELECT COUNT(*) FROM querys WHERE status = %s AND domain=%s ", (status, domain))
            total_count = cursor.fetchone()['COUNT(*)']

            # Get paginated results
            cursor.execute(
                "SELECT * FROM querys WHERE status = %s AND domain=%s ORDER BY updatedAt DESC LIMIT %s OFFSET %s",
                (status, domain, per_page, offset)
            )
            queries = cursor.fetchall()
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM querys WHERE status = %s", (status,))
            total_count = cursor.fetchone()['COUNT(*)']
            # Get paginated results
            cursor.execute(
                "SELECT * FROM querys WHERE status = %s ORDER BY updatedAt DESC LIMIT %s OFFSET %s",
                (status, per_page, offset)
            )
            queries = cursor.fetchall()

    return jsonify({
        'page': page,
        'per_page': per_page,
        'total_items': total_count,
        'data': queries
    })


@app.route('/queries', methods=['POST'])
def create_query():
    data = request.get_json() or {}
    email = data.get('emailId')
    user_name = data.get('userName')
    message = data.get('message')
    domain = data.get('domain')

    if not all([email, user_name, message, domain]):
        abort(400, 'emailId, userName, message and domain are required')

    timestamp = datetime.now()
    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "INSERT INTO querys (emailId, userName, message, domain, status, updatedAt)"
            " VALUES (%s, %s, %s, %s, %s,%s)",
            (email, user_name, message, domain, 'pending', timestamp)
        )
        query_id = cursor.lastrowid
        cursor.execute(
            "SELECT * FROM querys WHERE id = %s", (query_id,)
        )
        new_query = cursor.fetchone()

    return jsonify(new_query), 201


@app.route('/queries/<int:query_id>/resolve', methods=['PUT'])
def resolve_query(query_id):
    data = request.get_json() or {}
    resolved_by = data.get('resolvedBy')
    agent_id = data.get('agentId')
    if not resolved_by:
        abort(400, 'resolvedBy is required')
    timestamp = datetime.now()
    with get_db_cursor() as (conn, cursor):
        cursor.execute(
            "UPDATE querys SET status = %s, resolvedBy = %s, updatedAt = %s, agent_id = %s WHERE id = %s",
            ('resolved', resolved_by, timestamp, agent_id, query_id)
        )
        cursor.execute("SELECT * FROM querys WHERE id = %s", (query_id,))
        updated_query = cursor.fetchone()

    return jsonify(updated_query)


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001)
