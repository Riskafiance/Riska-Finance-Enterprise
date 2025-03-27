import os
import sqlite3
from datetime import datetime
from flask import Flask, request, render_template, send_file, redirect, url_for, abort, after_this_request
import tempfile

app = Flask(__name__, template_folder="templates", static_folder="static")
DB_FILE = "accounting.db"

# Initialize database
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Create accounts table if it doesn't exist
        cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT UNIQUE NOT NULL,
                            balance REAL DEFAULT 0
                          )''')
        
        # Create transactions table if it doesn't exist
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            date TEXT,
                            account_id INTEGER,
                            description TEXT,
                            debit REAL,
                            credit REAL,
                            FOREIGN KEY(account_id) REFERENCES accounts(id)
                          )''')
        
        conn.commit()

# Helper function to insert a transaction and update account balance
def insert_transaction(cursor, date, account_id, description, debit, credit):
    cursor.execute("INSERT INTO transactions (date, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                   (date, account_id, description, debit, credit))
    cursor.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (debit - credit, account_id))

# Validate date input
def validate_date(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return None

# Validate amount input
def validate_amount(amount_str):
    try:
        return float(amount_str)
    except ValueError:
        return None

@app.route('/')
def index():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Fetch account details with balance and last updated date
        cursor.execute('''SELECT a.id, a.name, a.balance, MAX(t.date) as last_updated
                          FROM accounts a
                          LEFT JOIN transactions t ON a.id = t.account_id
                          GROUP BY a.id''')
        accounts = cursor.fetchall()
    return render_template("index.html", accounts=accounts)

@app.route('/home')
def home():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Calculate total number of accounts
        cursor.execute("SELECT COUNT(*) FROM accounts")
        total_accounts = cursor.fetchone()[0]
        
        # Calculate total number of transactions
        cursor.execute("SELECT COUNT(*) FROM transactions")
        total_transactions = cursor.fetchone()[0]
        
        # Calculate total balance across all accounts
        cursor.execute("SELECT SUM(balance) FROM accounts")
        total_balance = cursor.fetchone()[0] or 0  # Default to 0 if no accounts exist
    
    return render_template("home.html", total_accounts=total_accounts, total_transactions=total_transactions, total_balance=total_balance)

@app.route('/journal_entry', methods=['GET', 'POST'])
def journal_entry():
    if request.method == 'POST':
        date = request.form.get('date')
        debit_accounts = request.form.getlist('debit_account')
        debit_amounts = request.form.getlist('debit_amount')
        debit_descriptions = request.form.getlist('debit_description')
        credit_accounts = request.form.getlist('credit_account')
        credit_amounts = request.form.getlist('credit_amount')
        credit_descriptions = request.form.getlist('credit_description')

        # Validate date
        date = validate_date(date)
        if not date:
            return "Invalid date format. Use YYYY-MM-DD.", 400

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                # Insert debit transactions
                for account_id, amount, description in zip(debit_accounts, debit_amounts, debit_descriptions):
                    amount = validate_amount(amount)
                    if amount is not None:
                        insert_transaction(cursor, date, account_id, description, amount, 0)
                
                # Insert credit transactions
                for account_id, amount, description in zip(credit_accounts, credit_amounts, credit_descriptions):
                    amount = validate_amount(amount)
                    if amount is not None:
                        insert_transaction(cursor, date, account_id, description, 0, amount)
                
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                return f"An error occurred: {str(e)}", 500

        return redirect(url_for('index'))
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Fetch all accounts for the dropdown
        cursor.execute("SELECT id, name FROM accounts")
        accounts = cursor.fetchall()
    return render_template("journal_entry.html", accounts=accounts)

@app.route('/create_account', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            return "Account name cannot be empty.", 400

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO accounts (name) VALUES (?)", (name,))
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                return "Account name already exists.", 400

        return redirect(url_for('index'))
    return render_template("create_account.html")

@app.route('/delete_account/<int:account_id>', methods=['POST'])
def delete_account(account_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        try:
            # Delete the account
            cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            # Delete associated transactions
            cursor.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            return f"An error occurred: {str(e)}", 500

    return redirect(url_for('index'))

@app.route('/account/<int:account_id>')
def account_details(account_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Fetch account details
        cursor.execute("SELECT id, name, balance FROM accounts WHERE id = ?", (account_id,))
        account = cursor.fetchone()
        
        if not account:
            return "Account not found.", 404

        # Fetch transactions for the account
        cursor.execute('''SELECT date, description, debit, credit
                          FROM transactions
                          WHERE account_id = ?
                          ORDER BY date''', (account_id,))
        transactions = cursor.fetchall()
    
    return render_template("account_details.html", account=account, transactions=transactions)

@app.route('/add_transaction_page', methods=['GET', 'POST'])
def add_transaction_page():
    if request.method == 'POST':
        date = request.form.get('date')
        description = request.form.get('description')
        amount = request.form.get('amount')
        category = request.form.get('category')
        account_id = request.form.get('account')

        # Validate inputs
        date = validate_date(date)
        if not date:
            return "Invalid date format. Use YYYY-MM-DD.", 400

        amount = validate_amount(amount)
        if amount is None:
            return "Invalid amount.", 400

        if category not in ["Debit", "Credit"]:
            return "Invalid transaction category.", 400

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                if category == "Debit":
                    insert_transaction(cursor, date, account_id, description, amount, 0)
                elif category == "Credit":
                    insert_transaction(cursor, date, account_id, description, 0, amount)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                return f"An error occurred: {str(e)}", 500

        return redirect(url_for('index'))
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Fetch all accounts for the dropdown
        cursor.execute("SELECT id, name, balance FROM accounts")
        accounts = cursor.fetchall()
    return render_template("add_transaction.html", accounts=accounts)

@app.route('/download_journal_report', methods=['GET'])
def download_journal_report():
    account_ids = request.args.getlist('account_id')  # Get the selected account IDs
    start_date = request.args.get('start_date')       # Get the start date
    end_date = request.args.get('end_date')           # Get the end date

    if not account_ids:
        return "No accounts selected for the report.", 400

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Fetch journal entries for the selected accounts and date range
        query = '''SELECT t.date, a.name, t.description, t.debit, t.credit
                   FROM transactions t
                   JOIN accounts a ON t.account_id = a.id
                   WHERE t.account_id IN ({})'''.format(','.join(['?'] * len(account_ids)))
        params = account_ids

        # Add date range filtering if provided
        if start_date and end_date:
            query += " AND t.date BETWEEN ? AND ?"
            params.extend([start_date, end_date])
        elif start_date:
            query += " AND t.date >= ?"
            params.append(start_date)
        elif end_date:
            query += " AND t.date <= ?"
            params.append(end_date)

        query += " ORDER BY t.date"
        cursor.execute(query, tuple(params))
        journal_entries = cursor.fetchall()
    
    # Format the report as a text file
    report_content = f"Journal Entries Report for Accounts: {', '.join(account_ids)}\n\n"
    if start_date or end_date:
        report_content += f"Date Range: {start_date or 'Start'} to {end_date or 'End'}\n\n"
    report_content += "Date\t\tAccount\t\tDescription\t\tDebit\t\tCredit\n"
    report_content += "-" * 80 + "\n"
    for entry in journal_entries:
        date, account, description, debit, credit = entry
        report_content += f"{date}\t{account}\t{description}\t{debit}\t{credit}\n"
    
    # Save the report to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='w') as temp_file:
        temp_file.write(report_content)
        temp_file_path = temp_file.name

    # Ensure the file is deleted after the response is sent
    @after_this_request
    def cleanup(response):
        try:
            os.remove(temp_file_path)
        except Exception as e:
            app.logger.error(f"Error deleting temporary file: {e}")
        return response

    # Send the file for download
    return send_file(temp_file_path, as_attachment=True, download_name="journal_report.txt")

if __name__ == '__main__':
    init_db()
    app.run(debug=True)