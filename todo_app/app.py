import os
import logging
from flask import Flask, render_template, jsonify, request
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Default MongoDB URI and Database Name
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DATABASE = os.environ.get('MONGO_DATABASE', 'todo')

# Initialize MongoDB client and collection variables
client = None
db = None
tasks_collection = None
boards_collection = None
columns_collection = None
counters_collection = None  # Add counters collection

def connect_to_mongodb():
    """
    Establish a connection to MongoDB and initialize the database and collections.
    This function handles connection errors and sets the global database and collection variables.
    """
    global client, db, tasks_collection, boards_collection, columns_collection, counters_collection
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ping')  # Check connection
        logging.info(f"Successfully connected to MongoDB at: {MONGO_URI}")
        db = client[MONGO_DATABASE]
        tasks_collection = db['tasks']
        boards_collection = db['boards']
        columns_collection = db['columns']
        counters_collection = db['counters']  # Initialize counters collection
    except Exception as e:
        logging.error(f"Failed to connect to MongoDB at: {MONGO_URI}. Error: {e}")
        # Set to None to prevent errors in route handlers
        client = None
        db = None
        tasks_collection = None
        boards_collection = None
        columns_collection = None
        counters_collection = None
        # IMPORTANT:  Raise the exception to halt app initialization
        raise

# Call connect_to_mongodb when the app starts
try:
    connect_to_mongodb()
except Exception as e:
    # Handle the exception raised by connect_to_mongodb
    logging.critical("Application startup failed: Could not connect to MongoDB")
    #  Consider a more graceful shutdown,  don't start the app.
    exit(1)


@app.route('/')
def kanban_board():
    """
    Render the main Kanban board HTML page.
    """
    return render_template('kanban_board.html')

# Flag to ensure default columns are created only once
default_columns_initialized = False

@app.before_request
def ensure_default_columns():
    """
    Ensure that the default columns (Back Log, In Progress, Done) exist in the database.
    """
    global default_columns_initialized
    if default_columns_initialized:
        return

    if columns_collection is None:
        logging.error("Database connection failed. Cannot ensure default columns.")
        return

    default_columns = ['Back Log', 'In Progress', 'Done']
    for index, column_name in enumerate(default_columns):
        if not columns_collection.find_one({'name': column_name}):
            columns_collection.insert_one({
                'board_id': 'default_board',
                'name': column_name,
                'order': index
            })
            logging.info(f"Default column '{column_name}' created.")

    default_columns_initialized = True

@app.route('/api/board/<string:board_id>', methods=['GET'])
def get_board_data(board_id):
    """
    Retrieve data for a specific Kanban board, including columns and cards.

    Args:
        board_id (str): The ID of the board to retrieve.

    Returns:
        jsonify: A JSON response containing the board data or an error message.
    """
    if columns_collection is None:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        # Ensure default columns exist before fetching board data
        ensure_default_columns()

        columns = list(columns_collection.find({'board_id': board_id}).sort('order'))
        board_data = {
            'id': board_id,
            'name': 'My Kanban Board',
            'columns': []
        }

        for column in columns:
            tasks = list(tasks_collection.find({'column_id': str(column['_id'])}).sort('order')) if tasks_collection else []
            board_data['columns'].append({
                'id': str(column['_id']),
                'name': column['name'],
                'cards': [{
                    'id': str(task['_id']),
                    'title': task.get('title', 'No Title'),
                    'assignee': task.get('assignee'),
                    'due_date': task.get('due_date'),
                    'task_id': task.get('task_id'),
                    'status': column['name']  # Include status based on column name
                } for task in tasks]
            })
        return jsonify(board_data)
    except Exception as e:
        logging.error(f"Error fetching board data: {e}")
        return jsonify({'error': f'Failed to fetch board data: {e}'}), 500


@app.route('/api/boards/<string:board_id>/columns', methods=['POST'])
def create_column(board_id):
    """
    Create a new column for a specified Kanban board.

    Args:
        board_id (str): The ID of the board to add the column to.

    Returns:
        jsonify: A JSON response indicating success or failure, including the new column's ID.
    """
    if columns_collection is None:
        return jsonify({'error': 'Database connection failed'}), 500

    name = request.form.get('name')
    if not name:
        return jsonify({'success': False, 'error': 'Column name is required'}), 400

    try:
        last_column = columns_collection.find_one({'board_id': board_id}, sort=[('order', -1)])
        new_order = (last_column['order'] + 1) if last_column else 0
        new_column = {'board_id': board_id, 'name': name, 'order': new_order}
        result = columns_collection.insert_one(new_column)
        logging.info(f"Column '{name}' created with ID: {str(result.inserted_id)} for board: {board_id}")
        return jsonify({'success': True, 'new_column_id': str(result.inserted_id)})
    except Exception as e:
        logging.error(f"Error creating column: {e}")
        return jsonify({'success': False, 'error': f'Failed to create column: {e}'}), 500



@app.route('/api/columns/<string:column_id>/cards', methods=['POST'])
def create_card(column_id):
    """
    Create a new card in a specified column.

    Args:
        column_id (str): The ID of the column to add the card to.

    Returns:
        jsonify: A JSON response indicating success or failure, including the new card's ID.
    """
    if tasks_collection is None or counters_collection is None:
        return jsonify({'error': 'Database connection failed'}), 500

    title = request.form.get('title')
    board_id = request.form.get('board_id')  #  added board_id
    assignee = request.form.get('assignee')
    due_date_str = request.form.get('due_date')

    if not title or not board_id: # changed from title and board_id
        return jsonify({'success': False, 'error': 'Title and board_id are required'}), 400

    try:
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d') if due_date_str else None

        # Find the first column.  This is the change.
        first_column = columns_collection.find_one({'board_id': board_id}, sort=[('order', 1)])
        if first_column:
            column_id = str(first_column['_id'])  # Use the ID of the first column
        else:
            return jsonify({'success': False, 'error': 'No columns found for this board'}), 400

        # Get the next sequence number
        counter = counters_collection.find_one_and_update(
            {'name': 'task_counter'},
            {'$inc': {'seq': 1}},
            upsert=True,  # Create if it doesn't exist
            return_document=True  # Return the updated document
        )
        task_number = counter['seq']
        task_id = f"Task-{task_number}"

        last_card = tasks_collection.find_one({'column_id': column_id}, sort=[('order', -1)])
        new_order = (last_card['order'] + 1) if last_card else 0
        new_card = {
            'board_id': board_id,  # Added board_id
            'column_id': column_id,
            'title': title,
            'order': new_order,
            'assignee': assignee,
            'due_date': due_date,
            'task_id': task_id  # Include the unique task ID
        }
        result = tasks_collection.insert_one(new_card)
        logging.info(f"Card '{title}' created with ID: {str(result.inserted_id)} in column: {column_id}, Board: {board_id}, Assignee: {assignee}, Due Date: {due_date}, Task ID: {task_id}")
        return jsonify({'success': True, 'new_card_id': str(result.inserted_id), 'task_id': task_id})  # Return the task_id
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid date format. Please use-MM-DD'}), 400
    except Exception as e:
        logging.error(f"Error creating card: {e}")
        return jsonify({'success': False, 'error': f'Failed to create card: {e}'}), 500



@app.route('/api/cards/<string:card_id>/move', methods=['POST'])
def move_card(card_id):
    """
    Move a card to a different column and update its status.

    Args:
        card_id (str): The ID of the card to move.

    Returns:
        jsonify: A JSON response indicating success or failure.
    """
    if tasks_collection is None or columns_collection is None:
        return jsonify({'error': 'Database connection failed'}), 500

    new_column_id = request.form.get('new_column_id')
    if not new_column_id:
        return jsonify({'success': False, 'error': 'New column ID is required'}), 400

    try:
        # Fetch the new column to get its name
        new_column = columns_collection.find_one({'_id': ObjectId(new_column_id)})
        if not new_column:
            return jsonify({'success': False, 'error': 'New column not found'}), 404

        # Update the card's column and status
        result = tasks_collection.update_one(
            {'_id': ObjectId(card_id)},
            {'$set': {'column_id': new_column_id, 'status': new_column['name']}}
        )
        if result.modified_count > 0:
            logging.info(f"Card {card_id} moved to column {new_column_id} with status '{new_column['name']}'")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Card not found or column not updated'}), 404
    except Exception as e:
        logging.error(f"Error moving card: {e}")
        return jsonify({'success': False, 'error': f'Failed to move card: {e}'}), 500



@app.route('/api/cards/<string:card_id>', methods=['DELETE'])
def delete_card(card_id):
    """
    Delete a card.

    Args:
        card_id (str): The ID of the card to delete.

    Returns:
        jsonify: A JSON response indicating success or failure.
    """
    if tasks_collection is None:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        result = tasks_collection.delete_one({'_id': ObjectId(card_id)})
        if result.deleted_count > 0:
            logging.info(f"Card {card_id} deleted")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Card not found'}), 404
    except Exception as e:
        logging.error(f"Error deleting card: {e}")
        return jsonify({'success': False, 'error': f'Failed to delete card: {e}'}), 500


@app.route('/api/columns/<string:column_id>', methods=['DELETE'])
def delete_column(column_id):
    """
    Delete a column and all its associated cards.

    Args:
        column_id (str): The ID of the column to delete.

    Returns:
        jsonify: A JSON response indicating success or failure.
    """
    if columns_collection is None or tasks_collection is None:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        # Delete all cards in the column
        tasks_collection.delete_many({'column_id': column_id})
        # Delete the column itself
        result = columns_collection.delete_one({'_id': ObjectId(column_id)})
        if result.deleted_count > 0:
            logging.info(f"Column {column_id} and its cards deleted")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Column not found'}), 404
    except Exception as e:
        logging.error(f"Error deleting column: {e}")
        return jsonify({'success': False, 'error': f'Failed to delete column: {e}'}), 500


if __name__ == '__main__':
    # moved .env creation to be conditional.
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("MONGO_URI=mongodb://localhost:27017/\n")
            f.write("MONGO_DATABASE=todo\n")
        print("Created a default .env file. Please adjust MongoDB connection details if necessary.")
    logging.info("Flask application starting...")
    app.run(debug=True)
