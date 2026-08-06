import os

import mysql.connector
from flask import Flask, jsonify, request
from flask_cors import CORS
import bcrypt
from dotenv import load_dotenv

# Read configuration from the .env sitting next to this file (never commit it),
# so the server starts correctly from any working directory.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# MySQL Connection -- values come from the environment so no credential
# ever lives in source control. See .env.example for the required keys.
if not os.environ.get("DB_PASSWORD"):
    raise RuntimeError(
        "DB_PASSWORD is not set. Copy .env.example to .env and fill in your "
        "database credentials before starting the server."
    )

db_config = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ.get("DB_NAME", "partnerportaldb"),
}

def fetch_partners_from_db(filters=None):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        
        query = "SELECT * FROM partners"
        conditions = []
        params = []
        if filters:
            # Values are bound as parameters, never interpolated into the SQL
            # string -- otherwise a filter value could inject arbitrary SQL.
            if 'OrganizationType' in filters and filters['OrganizationType'] != 'All':
                conditions.append("OrganizationType LIKE %s")
                params.append(f"%{filters['OrganizationType']}%")
            if 'Location' in filters:
                conditions.append("Location LIKE %s")
                params.append(f"%{filters['Location']}%")
            if 'Resources' in filters:
                conditions.append("Resources LIKE %s")
                params.append(f"%{filters['Resources']}%")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        cursor.execute(query, params)
        partners = cursor.fetchall()
         
        cursor.close()
        connection.close()
        
        return partners
    except mysql.connector.Error as error:
        print(f"Error fetching partners: {error}")
        return []

# Route to fetch partners from MySQL and return as JSON
@app.route('/api/partners', methods=['GET'])
def get_partners():
    filters = {}
    if 'OrganizationType' in request.args:
        filters['OrganizationType'] = request.args.get('OrganizationType') 
    if 'Location' in request.args:
        filters['Location'] = request.args.get('Location')
    if 'Resources' in request.args:
        filters['Resources'] = request.args.get('Resources')
    
    partners = fetch_partners_from_db(filters)
    return jsonify(partners)

# Route for adding a partner
@app.route('/api/partners/add', methods=['POST'])
def add_partner():
    try:
        # Read with .get() so a missing field is a 400 the client can act on
        # rather than a KeyError surfacing as an opaque 500.
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        organization_type = (data.get('organization_type') or '').strip()
        expertise = (data.get('expertise') or '').strip()
        resources = (data.get('resources') or '').strip()
        email = (data.get('email') or '').strip()
        phone_number = (data.get('phone_number') or '').strip()
        location = (data.get('location') or '').strip()
        bio = (data.get('bio') or '').strip()

        if not name or not organization_type or not expertise:
            return jsonify({
                'error': 'Name, organization type and expertise are required.'
            }), 400

        connection = mysql.connector.connect(**db_config) # Establish connection
        cursor = connection.cursor()
        # Inserting partner data into database
        cursor.execute("""
            INSERT INTO partners (Name, OrganizationType, Expertise, Resources, Email, PhoneNumber, Location, Bio)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, organization_type, expertise, resources, email, phone_number, location, bio)) 
        
        connection.commit() 
        cursor.close()
        connection.close()

        return jsonify({'message': 'Partner added successfully'}), 201
    except Exception as e: # Exception handling
        app.logger.exception("Adding partner failed")
        return jsonify({'error': 'Could not add partner. Please try again.'}), 500

# NOTE: an unauthenticated DELETE /api/partners/remove used to live here. It had
# no caller in the frontend and let anyone on the internet delete any partner by
# name. It was removed rather than left dead. Bring it back once there are real
# sessions, scoped so an org can only delete its own record.

# Route for user registration
@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''

        if not name or not email or not password:
            return jsonify({'error': 'Name, email and password are all required.'}), 400

        # Hash the password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Insert user into database
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        try:
            cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, hashed_password.decode('utf-8')))
            connection.commit()
        except mysql.connector.IntegrityError:
            # `users.email` is UNIQUE, so this means the address is taken.
            return jsonify({'error': 'That email is already registered.'}), 409
        finally:
            cursor.close()
            connection.close()

        return jsonify({'message': 'User registered successfully', 'name': name}), 201
    except Exception as e:
        app.logger.exception("Registration failed")
        return jsonify({'error': 'Something went wrong. Please try again.'}), 500
    
@app.route('/api/onboarding', methods=['POST'])
def save_onboarding():
    try:
        data = request.get_json()

        organization_name = data.get('organization_name', '').strip()
        organization_type = data.get('organization_type', '').strip()
        location = data.get('location', '').strip()
        remote_friendly = bool(data.get('remote_friendly', False))
        needs = data.get('needs', '').strip()
        offers = data.get('offers', '').strip()
        preferred_partner_types = data.get('preferred_partner_types', '').strip()
        partnership_goals = data.get('partnership_goals', '').strip()
        description = data.get('description', '').strip()

        if not organization_name or not organization_type or not location or not needs or not offers:
            return jsonify({'error': 'Please fill in all required fields.'}), 400

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO onboarding_profiles
            (organization_name, organization_type, location, remote_friendly, needs, offers, preferred_partner_types, partnership_goals, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            organization_name,
            organization_type,
            location,
            remote_friendly,
            needs,
            offers,
            preferred_partner_types,
            partnership_goals,
            description
        ))

        new_id = cursor.lastrowid
        connection.commit()

        cursor.close()
        connection.close()

        return jsonify({
            'message': 'Onboarding profile saved successfully',
            'profile': {
                'id': new_id,
                'organization_name': organization_name,
                'organization_type': organization_type,
                'location': location,
                'remote_friendly': remote_friendly,
                'needs': needs,
                'offers': offers,
                'preferred_partner_types': preferred_partner_types,
                'partnership_goals': partnership_goals,
                'description': description
            }
        }), 201

    except Exception as e:
        app.logger.exception("Saving onboarding profile failed")
        return jsonify({'error': 'Could not save your profile. Please try again.'}), 500

# Route for user login
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json(silent=True) or {}
        # Normalised the same way as registration so casing never blocks login.
        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''

        if not email or not password:
            return jsonify({'error': 'Email and password are required.'}), 400

        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        connection.close()

        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            # The client stores `name` to greet the user, so it has to be
            # returned here -- never return the password hash.
            return jsonify({
                'message': 'Login successful',
                'name': user['name'],
                'email': user['email']
            }), 200
        else:
            return jsonify({'message': 'Invalid credentials'}), 401
    except Exception as e:
        app.logger.exception("Login failed")
        return jsonify({'error': 'Something went wrong. Please try again.'}), 500
    
def save_contact_message(name, phone, email, message):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        
        insert_query = "INSERT INTO contact_messages (name, phone, email, message) VALUES (%s, %s, %s, %s)"
        cursor.execute(insert_query, (name, phone, email, message))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return True
    except mysql.connector.Error as error:
        print(f"Error saving contact message: {error}")
        return False

@app.route('/api/contact', methods=['POST'])
def contact_form_submit():
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip()
        message = (data.get('message') or '').strip()

        if not name or not email or not message:
            return jsonify({'error': 'Name, email and message are required.'}), 400

        # Save the message to the database
        saved = save_contact_message(name, phone, email, message)

        if saved:
            return jsonify({'message': 'Message saved successfully'}), 201
        else:
            return jsonify({'error': 'Failed to save message'}), 500
    except Exception as e:
        app.logger.exception("Saving contact message failed")
        return jsonify({'error': 'Could not send your message. Please try again.'}), 500

if __name__ == '__main__':
    # Debug mode exposes an interactive console to anyone who can reach the
    # server, so it defaults to off and is opt-in via .env for local work.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=int(os.environ.get("PORT", 5000)))

# The database schema lives in `schema.sql` (and optional sample rows in
# `seed.sql`) so it can actually be executed, instead of drifting out of sync
# as commented-out text down here.
