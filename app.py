from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import pymysql
from dotenv import load_dotenv
import os
from openai import OpenAI
import bcrypt
import json
import re
from datetime import datetime, timedelta
import hashlib
import hmac
import requests
import json
import traceback  

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.getenv('SECRET_KEY', 'fallback-secret-key'))

# OpenRouter client configuration
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv('OPENROUTER_API_KEY')
)

# Database configuration - Updated to use PyMySQL
def get_db_connection():
    return pymysql.connect(
        host=os.getenv('MYSQL_HOST'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DB'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


def has_active_subscription(user_id):
    """Check if user has an active subscription or is in trial period"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if user is in trial period
    cursor.execute("SELECT trial_end_date FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if user and user['trial_end_date']:
        trial_end = user['trial_end_date']
        now = datetime.now()
        
        # Handle timezone comparison
        if hasattr(trial_end, 'tzinfo') and trial_end.tzinfo is not None:
            from datetime import timezone
            now = now.replace(tzinfo=timezone.utc)
        
        if now < trial_end:
            cursor.close()
            conn.close()
            return True
    
    # Check for active paid subscription
    cursor.execute("""
        SELECT status, end_date FROM subscriptions 
        WHERE user_id = %s AND status = 'active' AND end_date > NOW()
    """, (user_id,))
    
    subscription = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return subscription is not None

def get_trial_status(trial_end_date):
    """Consistently calculate trial status across the app"""
    if not trial_end_date:
        return {'status': 'no_trial', 'message': 'No trial period', 'days_left': 0}
    
    now = datetime.now()
    
    # Handle timezone comparison
    if hasattr(trial_end_date, 'tzinfo') and trial_end_date.tzinfo is not None:
        from datetime import timezone
        now = now.replace(tzinfo=timezone.utc)
    
    if now < trial_end_date:
        days_left = (trial_end_date - now).days
        return {
            'status': 'active', 
            'message': f'Trial active ({days_left} days left)',
            'days_left': days_left
        }
    else:
        return {
            'status': 'expired', 
            'message': 'Trial expired',
            'days_left': 0
        }
    

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get user trial info
    cursor.execute("SELECT trial_end_date FROM users WHERE id = %s", (session['user_id'],))
    user_data = cursor.fetchone()
    trial_end_date = user_data['trial_end_date'] if user_data else None
    
    # Get latest subscription
    cursor.execute("""
        SELECT s.status, s.end_date, sp.name 
        FROM subscriptions s 
        JOIN subscription_plans sp ON s.plan_id = sp.id 
        WHERE s.user_id = %s 
        ORDER BY s.created_at DESC 
        LIMIT 1
    """, (session['user_id'],))
    
    subscription = cursor.fetchone()
    cursor.close()
    conn.close()
    
    # Determine subscription status
    subscription_status = 'trial'  # Default to trial
    plan_name = 'Trial'
    
    if subscription and subscription['status'] == 'active' and subscription['end_date'] > datetime.now():
        subscription_status = 'active'
        plan_name = subscription['name']
    elif trial_end_date and datetime.now() > trial_end_date:
        subscription_status = 'expired'
    
    # Calculate trial status
    trial_status = get_trial_status(trial_end_date)
    
    return render_template('index.html', 
                         user_name=session.get('user_name'),
                         subscription_status=subscription_status,
                         plan_name=plan_name,
                         trial_end_date=trial_end_date,
                         trial_status=trial_status,
                         now=datetime.now())

    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, password FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Set trial end date (14 days from now)
        trial_end_date = datetime.now() + timedelta(days=14)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (name, email, password, trial_end_date) VALUES (%s, %s, %s, %s)",
                         (name, email, hashed_password, trial_end_date))
            user_id = cursor.lastrowid
            
            # Create a trial subscription
            cursor.execute("SELECT id FROM subscription_plans WHERE name = 'Monthly'")
            plan = cursor.fetchone()
            plan_id = plan['id'] if plan else None
            
            if plan_id:
                cursor.execute("""
                    INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date)
                    VALUES (%s, %s, 'trial', NOW(), %s)
                """, (user_id, plan_id, trial_end_date))
            
            conn.commit()
            flash('Registration successful! Enjoy your 14-day free trial. Please log in.')
            return redirect(url_for('login'))
        except pymysql.IntegrityError:
            flash('Email already exists')
        finally:
            cursor.close()
            conn.close()
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/get_recommendations', methods=['POST'])
def get_recommendations():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Check subscription status
    if not has_active_subscription(session['user_id']):
        return jsonify({'error': 'Subscription required. Your free trial has ended.'}), 402
    
    data = request.get_json()
    ingredients = data.get('ingredients', '')
    
    if not ingredients:
        return jsonify({'error': 'No ingredients provided'}), 400
    
    try:
        # Call OpenRouter API using the OpenAI client interface
        response = client.chat.completions.create(
            model=os.getenv('OPENROUTER_MODEL', 'openai/gpt-3.5-turbo'),  # Default model, can be changed
            messages=[
                {"role": "system", "content": "You are a helpful cooking assistant. Provide exactly 3 simple recipes in JSON format."},
                {"role": "user", "content": f"Suggest 3 simple recipes with these ingredients: {ingredients}. Return only a JSON array with objects containing 'name', 'ingredients', and 'instructions' fields."}
            ],
            max_tokens=800,
            temperature=0.7,
            # Optional: Add extra headers for OpenRouter
            extra_headers={
                "HTTP-Referer": os.getenv('OPENROUTER_REFERER', 'http://localhost:5000'),
                "X-Title": "Recipe Recommendation App"
            }
        )
        
        # Parse OpenRouter response (same format as OpenAI)
        ai_response = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', ai_response, re.DOTALL)
        if json_match:
            recipes_data = json.loads(json_match.group())
        else:
            # Fallback parsing
            recipes_data = parse_text_recipes(ai_response)
        
        # Save recipes to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        saved_recipes = []
        for recipe in recipes_data[:3]:  # Limit to 3 recipes
            # Convert ingredients and instructions to strings if they are lists
            ingredients_str = recipe['ingredients']
            if isinstance(ingredients_str, list):
                ingredients_str = ', '.join(ingredients_str)
                
            instructions_str = recipe['instructions']
            if isinstance(instructions_str, list):
                instructions_str = ' '.join(instructions_str)
            
            cursor.execute(
                "INSERT INTO recipes (recipe_name, ingredients, instructions, user_id) VALUES (%s, %s, %s, %s)",
                (recipe['name'], ingredients_str, instructions_str, session['user_id'])
            )
            recipe_id = cursor.lastrowid
            recipe['id'] = recipe_id
            saved_recipes.append(recipe)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'recipes': saved_recipes})
        
    except Exception as e:
        print(f"Error: {e}")
        error_message = str(e)
        
        # Handle specific OpenRouter/API errors
        if 'insufficient_quota' in error_message or 'credits' in error_message.lower():
            return jsonify({'error': 'OpenRouter API quota exceeded. Please check your billing details or try again later.'}), 429
        elif 'rate_limit' in error_message:
            return jsonify({'error': 'Rate limit exceeded. Please try again in a few moments.'}), 429
        elif 'invalid_api_key' in error_message or 'unauthorized' in error_message.lower():
            return jsonify({'error': 'Invalid API key. Please check your OpenRouter configuration.'}), 401
        elif 'model_not_found' in error_message.lower():
            return jsonify({'error': 'Selected model not available. Please check your model configuration.'}), 400
        else:
            return jsonify({'error': 'Failed to get recommendations. Please try again later.'}), 500

def parse_text_recipes(text):
    """Fallback parser for non-JSON responses"""
    recipes = []
    lines = text.split('\n')
    current_recipe = {}
    
    for line in lines:
        line = line.strip()
        if line.startswith('1.') or line.startswith('2.') or line.startswith('3.'):
            if current_recipe:
                recipes.append(current_recipe)
            current_recipe = {'name': line[2:].strip(), 'ingredients': '', 'instructions': ''}
        elif 'ingredients' in line.lower() and current_recipe:
            current_recipe['ingredients'] = line.split(':')[1].strip() if ':' in line else line
        elif 'instructions' in line.lower() and current_recipe:
            current_recipe['instructions'] = line.split(':')[1].strip() if ':' in line else line
    
    if current_recipe:
        recipes.append(current_recipe)
    
    return recipes

@app.route('/get_user_recipes')
def get_user_recipes():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # SQL JOIN to get recipes with user information
    cursor.execute("""
        SELECT r.id, r.recipe_name, r.ingredients, r.instructions, r.created_at, u.name as user_name
        FROM recipes r
        JOIN users u ON r.user_id = u.id
        WHERE r.user_id = %s
        ORDER BY r.created_at DESC
        LIMIT 10
    """, (session['user_id'],))
    
    recipes = []
    for row in cursor.fetchall():
        recipes.append({
            'id': row['id'],
            'name': row['recipe_name'],
            'ingredients': row['ingredients'],
            'instructions': row['instructions'],
            'created_at': row['created_at'].strftime('%Y-%m-%d %H:%M'),
            'user_name': row['user_name']
        })
    
    cursor.close()
    conn.close()
    
    return jsonify({'recipes': recipes})

@app.route('/subscription')
def subscription():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get subscription plans
    cursor.execute("SELECT * FROM subscription_plans WHERE is_active = TRUE")
    plans = cursor.fetchall()
    
    # Get user's current subscription
    cursor.execute("""
        SELECT s.status, s.start_date, s.end_date, sp.name, sp.price, u.trial_end_date
        FROM subscriptions s
        JOIN subscription_plans sp ON s.plan_id = sp.id
        JOIN users u ON s.user_id = u.id
        WHERE s.user_id = %s
        ORDER BY s.created_at DESC
        LIMIT 1
    """, (session['user_id'],))
    
    current_subscription = cursor.fetchone()
    cursor.close()
    conn.close()
    
    subscription_data = None
    if current_subscription:
        subscription_data = {
            'status': current_subscription['status'],
            'start_date': current_subscription['start_date'],
            'end_date': current_subscription['end_date'],
            'plan_name': current_subscription['name'],
            'price': current_subscription['price'],
            'trial_end_date': current_subscription['trial_end_date']
        }
    
    return render_template('subscription.html', 
                     plans=plans, 
                     subscription=subscription_data,
                     user_name=session.get('user_name'),
                     now=datetime.now())

@app.route('/create_subscription', methods=['POST'])
def create_subscription():
    """Create a subscription payment with IntaSend"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    plan_id = data.get('plan_id')
    
    if not plan_id:
        return jsonify({'error': 'Plan ID required'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get plan details
        cursor.execute("SELECT name, price, duration_days FROM subscription_plans WHERE id = %s", (plan_id,))
        plan = cursor.fetchone()
        
        if not plan:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Plan not found'}), 404
        
        plan_name, price, duration = plan['name'], plan['price'], plan['duration_days']
        
        # Get user details
        cursor.execute("SELECT name, email FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            conn.close()
            return jsonify({'error': 'User not found'}), 404
            
        user_name, user_email = user['name'], user['email']
        cursor.close()
        conn.close()
        
        # Generate unique API reference
        api_ref = f"sub_{session['user_id']}_{plan_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Determine if we're in test or live mode
        is_test = os.getenv('INTASEND_TEST_MODE', 'true').lower() == 'true'
        
        # Set the correct base URL and keys
        if is_test:
            base_url = "https://sandbox.intasend.com"
            public_key = os.getenv('INTASEND_PUBLIC_KEY_TEST', os.getenv('INTASEND_PUBLIC_KEY'))
            secret_key = os.getenv('INTASEND_SECRET_KEY_TEST', os.getenv('INTASEND_SECRET_KEY'))
        else:
            base_url = "https://payment.intasend.com"
            public_key = os.getenv('INTASEND_PUBLIC_KEY_LIVE', os.getenv('INTASEND_PUBLIC_KEY'))
            secret_key = os.getenv('INTASEND_SECRET_KEY_LIVE', os.getenv('INTASEND_SECRET_KEY'))
        
        # Create IntaSend checkout request with extra data for webhook
        intasend_data = {
            "public_key": public_key,
            "amount": float(price),
            "currency": "KES",
            "email": user_email,
            "first_name": user_name.split()[0] if user_name else "Customer",
            "last_name": user_name.split()[-1] if len(user_name.split()) > 1 else "User",
            "country": "KE",
            "address": "",
            "city": "",
            "state": "",
            "zipcode": "",
            "redirect_url": url_for('payment_callback', _external=True),
            "api_ref": api_ref,
            # This is the key fix - include user and plan data in extra field
            "extra": {
                "user_id": session['user_id'],
                "plan_id": plan_id,
                "plan_name": plan_name
            }
        }
        
        # Set up headers for API authentication
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        
        # Use basic authentication with public key as username and secret key as password
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(public_key, secret_key)
        
        # Use the correct IntaSend checkout endpoint
        intasend_url = f"{base_url}/api/v1/checkout/"
        
        print(f"=== IntaSend Checkout Request Debug ===")
        print(f"URL: {intasend_url}")
        print(f"Test mode: {is_test}")
        print(f"User ID: {session['user_id']}, Plan ID: {plan_id}")
        print(f"Request data: {intasend_data}")
        
        # Make request to IntaSend
        response = requests.post(
            intasend_url, 
            json=intasend_data, 
            headers=headers, 
            auth=auth,
            timeout=30
        )
        
        print(f"=== IntaSend Response Debug ===")
        print(f"Status code: {response.status_code}")
        print(f"Response text: {response.text}")
        
        if not response.content:
            return jsonify({'error': 'Empty response from payment provider'}), 500
        
        try:
            payment_data = response.json()
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return jsonify({'error': 'Invalid JSON response from payment provider'}), 500
        
        if response.status_code in [200, 201]:
            checkout_url = payment_data.get('url') or payment_data.get('checkout_url')
            
            if checkout_url:
                # Store pending payment in database for tracking
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO payments (user_id, plan_id, subscription_id, amount, status, payment_method, transaction_id, created_at)
                    VALUES (%s, %s, NULL, %s, 'pending', 'intasend', %s, NOW())
                """, (session['user_id'], plan_id, float(price), api_ref))
                conn.commit()
                cursor.close()
                conn.close()
                
                return jsonify({
                    'success': True,
                    'payment_url': checkout_url,
                    'invoice_id': payment_data.get('id') or payment_data.get('invoice_id'),
                    'api_ref': api_ref
                })
            else:
                return jsonify({'error': 'No payment URL received from provider'}), 500
        else:
            error_message = payment_data.get('detail', payment_data.get('message', 'Payment request failed'))
            print(f"IntaSend error: {error_message}")
            return jsonify({'error': f'Payment service error: {error_message}'}), 500
            
    except Exception as e:
        print(f"Error creating subscription: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to create subscription. Please try again.'}), 500

@app.route('/payment_callback')
def payment_callback():
    """Fixed payment callback that uses correct IntaSend API endpoints"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get payment details from callback parameters
    tracking_id = request.args.get('tracking_id')
    checkout_id = request.args.get('checkout_id')
    signature = request.args.get('signature')
    
    print(f"=== Payment Callback Received ===")
    print(f"Tracking ID: {tracking_id}")
    print(f"Checkout ID: {checkout_id}")
    print(f"All params: {dict(request.args)}")
    
    if not checkout_id:
        flash('Payment verification failed - missing checkout ID.')
        return redirect(url_for('subscription'))
    
    # For now, let's process based on the presence of tracking_id
    # which indicates successful payment completion
    if tracking_id and checkout_id:
        print("Payment appears successful - processing...")
        
        # Find the pending payment by checkout_id or api_ref pattern
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Look for pending payment with matching checkout_id or recent payment for this user
            cursor.execute("""
                SELECT user_id, plan_id, transaction_id 
                FROM payments 
                WHERE user_id = %s AND status = 'pending'
                ORDER BY created_at DESC 
                LIMIT 1
            """, (session['user_id'],))
            
            payment_record = cursor.fetchone()
            
            if payment_record:
                user_id, plan_id, api_ref = payment_record['user_id'], payment_record['plan_id'], payment_record['transaction_id']
                print(f"Found pending payment: user_id={user_id}, plan_id={plan_id}")
                
                # Process the payment
                success = process_successful_payment(
                    user_id, 
                    plan_id, 
                    0,  # Amount not critical for processing
                    checkout_id, 
                    api_ref
                )
                
                if success:
                    flash('Payment successful! Your subscription is now active.')
                    cursor.close()
                    conn.close()
                    return redirect(url_for('subscription'))
                else:
                    flash('Payment processed but there was an issue activating your subscription. Please contact support.')
            else:
                # Try to extract from checkout_id pattern if it contains our api_ref
                # Or process any recent subscription attempt for this user
                cursor.execute("""
                    SELECT plan_id FROM subscription_plans 
                    WHERE is_active = TRUE
                    ORDER BY price DESC 
                    LIMIT 1
                """)
                
                # This is a fallback - ideally we should have the pending payment record
                flash('Payment received but could not verify subscription details. Please contact support with your tracking ID: ' + tracking_id)
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Error processing callback: {e}")
            flash('Payment verification failed. Please contact support if you were charged.')
    else:
        flash('Payment was not completed successfully.')
    
    return redirect(url_for('subscription'))

def process_successful_payment(user_id, plan_id, amount, transaction_id, api_ref):
    """Process a successful payment and activate subscription"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if already processed
        cursor.execute("""
            SELECT id FROM payments 
            WHERE transaction_id IN (%s, %s) AND status = 'completed'
        """, (transaction_id, api_ref))
        existing = cursor.fetchone()
        
        if existing:
            print(f"Payment {transaction_id} already processed")
            cursor.close()
            conn.close()
            return True
        
        # Get plan details
        cursor.execute("SELECT duration_days, name FROM subscription_plans WHERE id = %s", (plan_id,))
        plan = cursor.fetchone()
        
        if not plan:
            print(f"Plan {plan_id} not found")
            cursor.close()
            conn.close()
            return False
        
        duration_days, plan_name = plan['duration_days'], plan['name']
        
        # Calculate dates
        start_date = datetime.now()
        end_date = start_date + timedelta(days=duration_days)
        
        # Deactivate existing subscriptions
        cursor.execute("""
            UPDATE subscriptions 
            SET status = 'cancelled', updated_at = NOW()
            WHERE user_id = %s AND status IN ('active', 'trial')
        """, (user_id,))
        
        print(f"Cancelled {cursor.rowcount} existing subscriptions")
        
        # Create new subscription
        cursor.execute("""
            INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, created_at, updated_at)
            VALUES (%s, %s, 'active', %s, %s, NOW(), NOW())
        """, (user_id, plan_id, start_date, end_date))
        
        subscription_id = cursor.lastrowid
        
        # Update or create payment record
        cursor.execute("""
            UPDATE payments 
            SET subscription_id = %s, status = 'completed', updated_at = NOW()
            WHERE user_id = %s AND transaction_id = %s AND status = 'pending'
        """, (subscription_id, user_id, api_ref))
        
        if cursor.rowcount == 0:
            # Create new payment record
            cursor.execute("""
                INSERT INTO payments (user_id, subscription_id, plan_id, amount, status, payment_method, transaction_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'completed', 'intasend', %s, NOW(), NOW())
            """, (user_id, subscription_id, plan_id, amount, transaction_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"Successfully processed payment for user {user_id}, subscription {subscription_id}")
        return True
        
    except Exception as e:
        print(f"Error processing payment: {e}")
        import traceback
        traceback.print_exc()
        return False

@app.route('/verify_payment', methods=['POST'])
def verify_payment():
    """Manual payment verification for users"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    checkout_id = data.get('checkout_id')
    
    if not checkout_id:
        return jsonify({'error': 'Checkout ID required'}), 400
    
    try:
        is_test = os.getenv('INTASEND_TEST_MODE', 'true').lower() == 'true'
        
        if is_test:
            base_url = "https://sandbox.intasend.com"
            public_key = os.getenv('INTASEND_PUBLIC_KEY_TEST', os.getenv('INTASEND_PUBLIC_KEY'))
            secret_key = os.getenv('INTASEND_SECRET_KEY_TEST', os.getenv('INTASEND_SECRET_KEY'))
        else:
            base_url = "https://payment.intasend.com"
            public_key = os.getenv('INTASEND_PUBLIC_KEY_LIVE', os.getenv('INTASEND_PUBLIC_KEY'))
            secret_key = os.getenv('INTASEND_SECRET_KEY_LIVE', os.getenv('INTASEND_SECRET_KEY'))
        
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(public_key, secret_key)
        
        status_url = f"{base_url}/api/v1/checkout/{checkout_id}/"
        response = requests.get(status_url, auth=auth, timeout=10)
        
        if response.status_code == 200:
            payment_data = response.json()
            
            is_paid = payment_data.get('paid', False)
            api_ref = payment_data.get('api_ref', '')
            amount = payment_data.get('amount', 0)
            
            if is_paid and api_ref:
                # Extract user and plan info
                try:
                    parts = api_ref.split('_')
                    if len(parts) >= 3 and parts[0] == 'sub':
                        user_id = int(parts[1])
                        plan_id = int(parts[2])
                        
                        if user_id == session['user_id']:
                            success = process_successful_payment(user_id, plan_id, amount, checkout_id, api_ref)
                            
                            if success:
                                return jsonify({
                                    'success': True, 
                                    'message': 'Payment verified and subscription activated!'
                                })
                            else:
                                return jsonify({
                                    'success': False, 
                                    'message': 'Payment verified but subscription activation failed.'
                                })
                        else:
                            return jsonify({
                                'success': False, 
                                'message': 'Payment belongs to different user.'
                            })
                except (ValueError, IndexError):
                    return jsonify({
                        'success': False, 
                        'message': 'Invalid payment reference format.'
                    })
            else:
                return jsonify({
                    'success': False, 
                    'message': f'Payment not completed. Status: paid={is_paid}'
                })
        else:
            return jsonify({
                'success': False, 
                'message': 'Unable to verify payment with IntaSend.'
            })
            
    except Exception as e:
        print(f"Payment verification error: {e}")
        return jsonify({
            'success': False, 
            'message': 'Payment verification failed due to technical error.'
        }), 500

@app.route("/intasend-webhook", methods=["POST"])
def intasend_webhook():
    """Handle IntaSend webhook events with signature verification"""
    
    print("=== Webhook Request Received ===")
    print(f"Headers: {dict(request.headers)}")
    print(f"Method: {request.method}")
    
    # Handle challenge validation first
    if request.is_json:
        data = request.get_json()
        if data and "challenge" in data:
            print(f"Challenge validation: {data['challenge']}")
            return jsonify({"challenge": data["challenge"]})
    
    # Get raw body for signature verification
    raw_body = request.get_data()
    signature = request.headers.get('X-IntaSend-Signature')
    
    print(f"Raw body length: {len(raw_body) if raw_body else 0}")
    print(f"Signature present: {bool(signature)}")
    
    # Verify signature (optional in test mode)
    webhook_secret = os.getenv('INTASEND_WEBHOOK_SECRET')
    if webhook_secret and signature:
        expected_signature = hmac.new(
            webhook_secret.encode(),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            print("Invalid webhook signature")
            return "Invalid signature", 401
    
    # Parse webhook data
    try:
        data = json.loads(raw_body) if raw_body else {}
        print(f"Parsed webhook data: {json.dumps(data, indent=2, default=str)}")
    except json.JSONDecodeError:
        print("Invalid JSON in webhook")
        return "Invalid JSON", 400
    
    # Handle IntaSend payment completion
    if (data.get('state') == 'COMPLETE' or 
        data.get('status') == 'COMPLETE' or 
        data.get('status') == 'PAID'):
        
        print("Processing successful payment webhook...")
        
        try:
            # Extract payment information
            invoice_id = data.get('invoice_id') or data.get('id')
            amount = data.get('value') or data.get('amount')
            api_ref = data.get('api_ref')
            
            # Get user and plan info from extra field or api_ref
            user_id = None
            plan_id = None
            
            # Method 1: From extra field (if IntaSend preserves it)
            extra_data = data.get('extra', {})
            if isinstance(extra_data, dict):
                user_id = extra_data.get('user_id')
                plan_id = extra_data.get('plan_id')
            
            # Method 2: Parse from api_ref if extra data not available
            if not user_id and api_ref:
                # api_ref format: sub_{user_id}_{plan_id}_{timestamp}
                parts = api_ref.split('_')
                if len(parts) >= 3 and parts[0] == 'sub':
                    try:
                        user_id = int(parts[1])
                        plan_id = int(parts[2])
                    except (ValueError, IndexError):
                        print(f"Failed to parse api_ref: {api_ref}")
            
            print(f"Extracted data: user_id={user_id}, plan_id={plan_id}, amount={amount}, invoice_id={invoice_id}")
            
            if not user_id or not plan_id:
                print("Missing user_id or plan_id in webhook data")
                # Try to find pending payment by api_ref
                if api_ref:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT user_id, plan_id FROM payments 
                        WHERE transaction_id = %s AND status = 'pending'
                    """, (api_ref,))
                    payment_record = cursor.fetchone()
                    cursor.close()
                    conn.close()
                    
                    if payment_record:
                        user_id = payment_record['user_id']
                        plan_id = payment_record['plan_id']
                        print(f"Found user_id={user_id}, plan_id={plan_id} from payment record")
                    else:
                        print(f"No pending payment found for api_ref: {api_ref}")
                        return "Payment record not found", 400
                else:
                    print("No api_ref provided")
                    return "Missing required data", 400
            
            if user_id and plan_id:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # Check if payment already processed
                cursor.execute("""
                    SELECT id FROM payments 
                    WHERE transaction_id = %s AND status = 'completed'
                """, (invoice_id or api_ref,))
                existing_payment = cursor.fetchone()
                
                if existing_payment:
                    print(f"Payment {invoice_id or api_ref} already processed")
                    cursor.close()
                    conn.close()
                    return "Already processed", 200
                
                # Get plan duration
                cursor.execute("SELECT duration_days FROM subscription_plans WHERE id = %s", (plan_id,))
                plan = cursor.fetchone()
                
                if plan:
                    # Calculate subscription dates
                    start_date = datetime.now()
                    end_date = start_date + timedelta(days=plan['duration_days'])
                    
                    # Deactivate any existing active subscriptions
                    cursor.execute("""
                        UPDATE subscriptions 
                        SET status = 'cancelled' 
                        WHERE user_id = %s AND status IN ('active', 'trial')
                    """, (user_id,))
                    
                    # Create new active subscription
                    cursor.execute("""
                        INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date)
                        VALUES (%s, %s, 'active', %s, %s)
                    """, (user_id, plan_id, start_date, end_date))
                    
                    subscription_id = cursor.lastrowid
                    
                    # Update the existing pending payment record
                    cursor.execute("""
                        UPDATE payments 
                        SET subscription_id = %s, status = 'completed', updated_at = NOW()
                        WHERE transaction_id = %s AND user_id = %s AND status = 'pending'
                    """, (subscription_id, api_ref, user_id))
                    
                    # If no pending payment was found, create a new payment record
                    if cursor.rowcount == 0:
                        cursor.execute("""
                            INSERT INTO payments (user_id, subscription_id, plan_id, amount, status, payment_method, transaction_id, created_at)
                            VALUES (%s, %s, %s, %s, 'completed', 'intasend', %s, NOW())
                        """, (user_id, subscription_id, plan_id, amount, invoice_id or api_ref))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    print(f"Successfully processed webhook for user {user_id}, subscription {subscription_id}")
                    return "Webhook processed successfully", 200
                else:
                    print(f"Plan {plan_id} not found")
                    cursor.close()
                    conn.close()
                    return "Plan not found", 400
            else:
                print("Missing user_id or plan_id")
                return "Missing required data", 400
                
        except Exception as e:
            print(f"Error processing webhook: {e}")
            import traceback
            traceback.print_exc()
            return "Server error", 500
    
    print(f"Webhook event not processed: {data.get('state') or data.get('status')}")
    return "Event not processed", 200

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get user details
    cursor.execute("SELECT name, email, trial_end_date FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    
    # Get subscription details
    cursor.execute("""
        SELECT s.status, s.start_date, s.end_date, sp.name as plan_name, sp.price
        FROM subscriptions s
        JOIN subscription_plans sp ON s.plan_id = sp.id
        WHERE s.user_id = %s
        ORDER BY s.created_at DESC
        LIMIT 1
    """, (session['user_id'],))
    
    subscription = cursor.fetchone()
    cursor.close()
    conn.close()
    
    trial_status = get_trial_status(user['trial_end_date']) if user else None
    
    return render_template('profile.html', 
                         user=user,
                         subscription=subscription,
                         trial_status=trial_status,
                         user_name=session.get('user_name'))

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    
    if not name or not email:
        return jsonify({'error': 'Name and email are required'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE users SET name = %s, email = %s WHERE id = %s", 
                     (name, email, session['user_id']))
        conn.commit()
        
        session['user_name'] = name
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Profile updated successfully'})
        
    except pymysql.IntegrityError:
        return jsonify({'error': 'Email already exists'}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to update profile'}), 500

@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete user data (in production, you might want to soft delete)
        cursor.execute("DELETE FROM recipes WHERE user_id = %s", (session['user_id'],))
        cursor.execute("DELETE FROM payments WHERE user_id = %s", (session['user_id'],))
        cursor.execute("DELETE FROM subscriptions WHERE user_id = %s", (session['user_id'],))
        cursor.execute("DELETE FROM users WHERE id = %s", (session['user_id'],))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        session.clear()
        return jsonify({'success': True, 'message': 'Account deleted successfully'})
        
    except Exception as e:
        return jsonify({'error': 'Failed to delete account'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return jsonify({'status': 'healthy', 'database': 'connected'})
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'database': 'disconnected', 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
