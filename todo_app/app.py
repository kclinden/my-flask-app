# -*- coding: utf-8 -*-
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
        # Explicitly set timeoutMS to handle potential network delays during connection
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) # 5 second timeout
        # The ismaster command is cheap and does not require auth.
        client.admin.command('ping')
        logging.info(f"Successfully connected to MongoDB at: {MONGO_URI.split('@')[-1]}") # Avoid logging credentials if present in URI
        db = client[MONGO_DATABASE]
        tasks_collection = db['tasks']
        boards_collection = db['boards'] # Although not used in add column, good practice to initialize
        columns_collection = db['columns']
        counters_collection = db['counters']  # Initialize counters collection
        logging.info(f"Using database: {MONGO_DATABASE}")
        logging.info(f"Collections initialized: tasks={tasks_collection is not None}, boards={boards_collection is not None}, columns={columns_collection is not None}, counters={counters_collection is not None}")
    except Exception as e:
        # Mask credentials in log output if they exist in the URI
        safe_uri = MONGO_URI.split('@')[-1] if '@' in MONGO_URI else MONGO_URI
        logging.error(f"Failed to connect to MongoDB at: {safe_uri}. Error: {e}")
        # Set to None to prevent errors in route handlers
        client = None
        db = None
        tasks_collection = None
        boards_collection = None
        columns_collection = None
        counters_collection = None
        # IMPORTANT: Raise the exception to halt app initialization if DB connection is critical
        raise ConnectionError(f"Could not connect to MongoDB: {e}")

# Call connect_to_mongodb when the app starts
try:
    connect_to_mongodb()
except ConnectionError as e:
    # Handle the exception raised by connect_to_mongodb
    logging.critical(f"Application startup failed: {e}")
    # Exit gracefully if DB is essential
    exit(1)


@app.route('/')
def kanban_board():
    """
    Render the main Kanban board HTML page.
    """
    # Check if DB connection is available before rendering
    if db is None or columns_collection is None:
         # You might want to render an error page or message
         logging.error("Database connection not available, cannot render Kanban board.")
         return "Error: Database connection is not available. Please check logs.", 503 # Service Unavailable
    return render_template('kanban_board.html')

# Flag to ensure default columns are created only once per app run
default_columns_initialized = False

@app.before_request
def ensure_default_columns():
    """
    Ensure that the default columns (Back Log, In Progress, Done) exist
    for the 'default_board'. Runs once per application lifecycle.
    """
    global default_columns_initialized
    # Only run if DB is connected and not already initialized
    if default_columns_initialized or columns_collection is None:
        return

    logging.info("Running ensure_default_columns check...")
    try:
        # Define the board ID for default columns
        default_board_id = 'default_board' # Make this explicit

        default_columns = ['Back Log', 'In Progress', 'Done']
        existing_columns = {col['name'] for col in columns_collection.find({'board_id': default_board_id}, {'name': 1})}

        # Find the highest current order for the default board
        last_column = columns_collection.find_one({'board_id': default_board_id}, sort=[('order', -1)])
        next_order = (last_column['order'] + 1) if last_column else 0

        for column_name in default_columns:
            if column_name not in existing_columns:
                columns_collection.insert_one({
                    'board_id': default_board_id,
                    'name': column_name,
                    'order': next_order
                })
                logging.info(f"Default column '{column_name}' created for board '{default_board_id}' with order {next_order}.")
                next_order += 1 # Increment order for the next default column
            else:
                 logging.debug(f"Default column '{column_name}' already exists for board '{default_board_id}'.")

        default_columns_initialized = True
        logging.info("Default columns check complete.")

    except Exception as e:
        logging.error(f"Error during ensure_default_columns: {e}")
        # Decide if this is critical. Maybe allow the app to continue but log severely.
        # For now, we just log the error. Consider implications if defaults MUST exist.


@app.route('/api/board/<string:board_id>', methods=['GET'])
def get_board_data(board_id):
    """
    Retrieve data for a specific Kanban board, including columns and cards.

    Args:
        board_id (str): The ID of the board to retrieve.

    Returns:
        jsonify: A JSON response containing the board data or an error message.
    """
    if columns_collection is None or tasks_collection is None:
        logging.error(f"get_board_data failed for board '{board_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    logging.info(f"Fetching board data for board_id: {board_id}")
    try:
        columns = list(columns_collection.find({'board_id': board_id}).sort('order'))
        logging.debug(f"Found {len(columns)} columns for board '{board_id}'.")

        board_data = {
            'id': board_id,
            'name': f"Kanban Board ({board_id})",
            'columns': []
        }

        # Priority mapping for sorting: high > medium > low
        priority_map = {'high': 3, 'medium': 2, 'low': 1}

        for column in columns:
            column_id_str = str(column['_id'])
            logging.debug(f"Fetching tasks for column_id: {column_id_str} (Name: {column['name']})")
            tasks = list(tasks_collection.find({'column_id': column_id_str}))

            # Apply priority mapping for sorting
            tasks.sort(key=lambda task: (priority_map.get(task.get('priority', 'low'), 1), task['order']), reverse=True)

            logging.debug(f"Found {len(tasks)} tasks for column '{column['name']}'.")

            board_data['columns'].append({
                'id': column_id_str,
                'name': column['name'],
                'cards': [{
                    'id': str(task['_id']),
                    'title': task.get('title', 'No Title'),
                    'assignee': task.get('assignee'),
                    'due_date': task['due_date'].strftime('%Y-%m-%d') if task.get('due_date') else None,
                    'task_id': task.get('task_id'),
                    'status': column['name'],
                    'priority': task.get('priority', 'low')
                } for task in tasks]
            })

        logging.info(f"Successfully retrieved data for board '{board_id}'.")
        return jsonify(board_data)

    except Exception as e:
        logging.error(f"Error fetching board data for board '{board_id}': {e}", exc_info=True)
        return jsonify({'error': f'Failed to fetch board data: {e}'}), 500


@app.route('/api/boards/<string:board_id>/columns', methods=['POST'])
def create_column(board_id):
    """
    Create a new column for a specified Kanban board.

    Expects 'name' in form data.

    Args:
        board_id (str): The ID of the board to add the column to.

    Returns:
        jsonify: A JSON response indicating success or failure, including the new column's ID.
    """
    logging.info(f"Received request to create column for board_id: {board_id}")

    if columns_collection is None:
        logging.error(f"Cannot create column for board '{board_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    # --- Enhanced Logging ---
    # Log the raw form data received (be careful if sensitive data is expected)
    logging.debug(f"Request form data: {request.form}")

    name = request.form.get('name')
    if not name:
        logging.warning(f"Column creation failed for board '{board_id}': Column name missing in request form data.")
        # Return success: False for consistency with other errors
        return jsonify({'success': False, 'error': 'Column name is required'}), 400
    else:
        logging.info(f"Attempting to create column with name: '{name}' for board '{board_id}'")


    try:
        # Determine the order of the new column
        # Find the column with the highest order *for this specific board*
        last_column = columns_collection.find_one({'board_id': board_id}, sort=[('order', -1)])

        if last_column:
            new_order = last_column.get('order', -1) + 1 # Use .get for safety, default to -1 so next is 0
            logging.debug(f"Last column order for board '{board_id}' is {last_column.get('order')}. New order will be {new_order}.")
        else:
            new_order = 0
            logging.debug(f"No existing columns found for board '{board_id}'. New order will be {new_order}.")

        # Check if a column with the same name already exists for this board
        existing_column = columns_collection.find_one({'board_id': board_id, 'name': name})
        if existing_column:
             logging.warning(f"Column creation aborted for board '{board_id}': Column with name '{name}' already exists.")
             return jsonify({'success': False, 'error': f"Column with name '{name}' already exists"}), 409 # Conflict

        # Insert the new column into the database
        new_column_doc = {'board_id': board_id, 'name': name, 'order': new_order}
        result = columns_collection.insert_one(new_column_doc)

        new_column_id = str(result.inserted_id)
        logging.info(f"Successfully created column '{name}' with ID: {new_column_id}, Order: {new_order} for board: {board_id}")

        # Return the newly created column details - frontend might need this
        return jsonify({
            'success': True,
            'message': 'Column created successfully',
            'column': { # Send back the created column data
                 'id': new_column_id,
                 'name': name,
                 'order': new_order,
                 'board_id': board_id,
                 'cards': [] # New column starts empty
            }
        }), 201 # HTTP status code for resource created

    except Exception as e:
        # --- Enhanced Logging ---
        logging.error(f"Error creating column '{name}' for board '{board_id}': {e}", exc_info=True) # Log traceback
        return jsonify({'success': False, 'error': f'Failed to create column: {e}'}), 500


@app.route('/api/columns/<string:column_id>/cards', methods=['POST'])
def create_card(column_id):
    """
    Create a new card in a specified column.

    Expects 'title', 'board_id', optionally 'assignee', 'due_date', 'priority' in form data.
    Cards are always added to the specified column_id, not necessarily the first column.

    Args:
        column_id (str): The ID of the column to add the card to.

    Returns:
        jsonify: A JSON response indicating success or failure, including the new card's ID.
    """
    logging.info(f"Received request to create card in column_id: {column_id}")

    if tasks_collection is None or counters_collection is None or columns_collection is None:
        logging.error(f"Cannot create card in column '{column_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    # --- Enhanced Logging ---
    logging.debug(f"Request form data: {request.form}")

    title = request.form.get('title')
    # board_id is needed to associate the card correctly and potentially for task ID generation context
    board_id = request.form.get('board_id')
    assignee = request.form.get('assignee')
    due_date_str = request.form.get('due_date')
    priority = request.form.get('priority', 'low')  # Default priority is 'low'

    if priority not in ['low', 'medium', 'high']:
        logging.warning(f"Invalid priority value '{priority}' for card creation.")
        return jsonify({'success': False, 'error': 'Invalid priority value. Must be low, medium, or high.'}), 400

    if not title:
        logging.warning(f"Card creation failed for column '{column_id}': Title is required.")
        return jsonify({'success': False, 'error': 'Title is required'}), 400
    # Although not strictly needed for insertion if column_id is known,
    # it's good practice to require board_id from the client for context.
    if not board_id:
         logging.warning(f"Card creation failed for column '{column_id}': board_id is required.")
         return jsonify({'success': False, 'error': 'board_id is required'}), 400


    logging.info(f"Attempting to create card with title: '{title}' in column '{column_id}' for board '{board_id}'.")

    try:
        # Validate column_id exists
        target_column = columns_collection.find_one({'_id': ObjectId(column_id), 'board_id': board_id})
        if not target_column:
             logging.error(f"Card creation failed: Column with ID '{column_id}' not found or does not belong to board '{board_id}'.")
             return jsonify({'success': False, 'error': 'Target column not found for the specified board'}), 404 # Not Found


        due_date = None
        if due_date_str:
            try:
                # Allow for empty string, treat as None
                if due_date_str.strip():
                    due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            except ValueError:
                logging.warning(f"Card creation failed for column '{column_id}': Invalid date format '{due_date_str}'.")
                return jsonify({'success': False, 'error': 'Invalid date format. Please use YYYY-MM-DD'}), 400


        # Get the next sequence number for Task ID (scoped per board or globally?)
        # Let's assume globally for simplicity as implemented
        counter_doc = counters_collection.find_one_and_update(
            {'name': 'task_counter'},
            {'$inc': {'seq': 1}},
            upsert=True,
            return_document=True # Use pymongo's constant if available, else use string
        )
        task_number = counter_doc['seq']
        task_id = f"Task-{task_number}" # Globally unique Task ID
        logging.info(f"Generated Task ID: {task_id}")


        # Determine order within the target column
        last_card = tasks_collection.find_one({'column_id': column_id}, sort=[('order', -1)])
        new_order = (last_card['order'] + 1) if last_card else 0
        logging.debug(f"Determined new card order in column '{column_id}': {new_order}")

        new_card_doc = {
            'board_id': board_id, # Store board_id on the card
            'column_id': column_id, # The target column
            'title': title,
            'order': new_order,
            'assignee': assignee if assignee else None, # Ensure None if empty
            'due_date': due_date, # Store as datetime object or None
            'task_id': task_id,
            'status': target_column['name'], # Set initial status based on column name
            'priority': priority, # Set priority
            'created_at': datetime.utcnow() # Add creation timestamp
        }
        result = tasks_collection.insert_one(new_card_doc)
        new_card_id = str(result.inserted_id)

        logging.info(f"Successfully created card '{title}' (ID: {new_card_id}) in column '{column_id}' (Board: {board_id}, TaskID: {task_id}, Order: {new_order}, Priority: {priority}).")

        # Return the full card data as created
        # Prepare the card data for JSON response (e.g., format date)
        response_card = {
             'id': new_card_id,
             'title': title,
             'assignee': assignee if assignee else None,
             'due_date': due_date.strftime('%Y-%m-%d') if due_date else None,
             'task_id': task_id,
             'status': target_column['name'],
             'priority': priority,
             'order': new_order, # Include order if frontend needs it
             'column_id': column_id # Include column_id if frontend needs it
        }

        return jsonify({
            'success': True,
            'message': 'Card created successfully',
            'card': response_card # Send back the created card data
            }), 201

    # Specific exception for invalid ObjectId format
    except bson.errors.InvalidId:
         logging.error(f"Card creation failed: Invalid column_id format '{column_id}'.")
         return jsonify({'success': False, 'error': 'Invalid column ID format'}), 400
    except Exception as e:
        logging.error(f"Error creating card '{title}' in column '{column_id}': {e}", exc_info=True) # Log traceback
        return jsonify({'success': False, 'error': f'Failed to create card: {e}'}), 500


@app.route('/api/cards/<string:card_id>/priority', methods=['PATCH'])
def update_card_priority(card_id):
    """
    Update the priority of a card.

    Expects 'priority' in form data.

    Args:
        card_id (str): The ID of the card to update.

    Returns:
        jsonify: A JSON response indicating success or failure.
    """
    logging.info(f"Received request to update priority for card_id: {card_id}")

    if tasks_collection is None:
        logging.error(f"Cannot update priority for card '{card_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    priority = request.form.get('priority')
    if priority not in ['low', 'medium', 'high']:
        logging.warning(f"Invalid priority value '{priority}' for card '{card_id}'.")
        return jsonify({'success': False, 'error': 'Invalid priority value. Must be low, medium, or high.'}), 400

    try:
        result = tasks_collection.update_one(
            {'_id': ObjectId(card_id)},
            {'$set': {'priority': priority}}
        )

        if result.matched_count == 0:
            logging.error(f"Priority update failed: Card with ID '{card_id}' not found.")
            return jsonify({'success': False, 'error': 'Card not found'}), 404
        elif result.modified_count > 0:
            logging.info(f"Successfully updated priority for card '{card_id}' to '{priority}'.")
            return jsonify({'success': True, 'message': 'Priority updated successfully'})
        else:
            logging.info(f"Card '{card_id}' priority was already set to '{priority}'.")
            return jsonify({'success': True, 'message': 'Priority already set to the specified value'})

    except bson.errors.InvalidId:
        logging.error(f"Priority update failed: Invalid card_id format '{card_id}'.")
        return jsonify({'success': False, 'error': 'Invalid card ID format'}), 400
    except Exception as e:
        logging.error(f"Error updating priority for card '{card_id}': {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Failed to update priority: {e}'}), 500


@app.route('/api/cards/<string:card_id>/move', methods=['POST'])
def move_card(card_id):
    """
    Move a card to a different column and update its order and status.

    Expects 'new_column_id', 'new_order' in form data.

    Args:
        card_id (str): The ID of the card to move.

    Returns:
        jsonify: A JSON response indicating success or failure.
    """
    logging.info(f"Received request to move card_id: {card_id}")

    if tasks_collection is None or columns_collection is None:
        logging.error(f"Cannot move card '{card_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    logging.debug(f"Request form data: {request.form}")

    new_column_id = request.form.get('new_column_id')
    # Frontend should ideally send the new order based on drop position
    new_order_str = request.form.get('new_order')

    if not new_column_id:
        logging.warning(f"Card move failed for card '{card_id}': new_column_id is required.")
        return jsonify({'success': False, 'error': 'New column ID is required'}), 400
    if new_order_str is None:
         logging.warning(f"Card move failed for card '{card_id}': new_order is required.")
         return jsonify({'success': False, 'error': 'New order is required'}), 400

    try:
        new_order = int(new_order_str)
    except ValueError:
         logging.warning(f"Card move failed for card '{card_id}': Invalid new_order value '{new_order_str}'.")
         return jsonify({'success': False, 'error': 'Invalid new order value, must be an integer.'}), 400


    try:
        # Fetch the target column to get its name (for status) and validate existence
        new_column = columns_collection.find_one({'_id': ObjectId(new_column_id)})
        if not new_column:
            logging.error(f"Card move failed for card '{card_id}': New column with ID '{new_column_id}' not found.")
            return jsonify({'success': False, 'error': 'New column not found'}), 404 # Not Found

        # TODO: Implement logic to re-order cards in the source and destination columns if necessary.
        # This simple implementation only updates the target card's column and order.
        # A full implementation would shift orders of other cards.

        # Update the card's column_id, order, and status
        result = tasks_collection.update_one(
            {'_id': ObjectId(card_id)},
            {'$set': {
                'column_id': new_column_id,
                'status': new_column['name'],
                'order': new_order,
                'updated_at': datetime.utcnow() # Add updated timestamp
                }
            }
        )

        if result.matched_count == 0:
             logging.error(f"Card move failed: Card with ID '{card_id}' not found.")
             return jsonify({'success': False, 'error': 'Card not found'}), 404
        elif result.modified_count > 0:
            logging.info(f"Successfully moved card '{card_id}' to column '{new_column_id}' (Name: {new_column['name']}) with order {new_order}.")
            # Consider returning the updated card data
            return jsonify({'success': True, 'message': 'Card moved successfully'})
        else:
             # Matched but not modified - perhaps data was already the same?
             logging.info(f"Card '{card_id}' was matched but not modified (already in target state?).")
             return jsonify({'success': True, 'message': 'Card already in target state'})

    # Specific exception for invalid ObjectId format
    except bson.errors.InvalidId:
         logging.error(f"Card move failed: Invalid card_id '{card_id}' or new_column_id '{new_column_id}' format.")
         # Distinguish which ID was invalid if possible, or give a general error
         return jsonify({'success': False, 'error': 'Invalid ID format provided'}), 400
    except Exception as e:
        logging.error(f"Error moving card '{card_id}' to column '{new_column_id}': {e}", exc_info=True)
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
    logging.info(f"Received request to delete card_id: {card_id}")

    if tasks_collection is None:
        logging.error(f"Cannot delete card '{card_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        result = tasks_collection.delete_one({'_id': ObjectId(card_id)})

        if result.deleted_count > 0:
            logging.info(f"Successfully deleted card '{card_id}'.")
            return jsonify({'success': True, 'message': 'Card deleted successfully'})
        else:
            logging.warning(f"Delete failed: Card with ID '{card_id}' not found.")
            return jsonify({'success': False, 'error': 'Card not found'}), 404

    # Specific exception for invalid ObjectId format
    except bson.errors.InvalidId:
         logging.error(f"Card deletion failed: Invalid card_id format '{card_id}'.")
         return jsonify({'success': False, 'error': 'Invalid card ID format'}), 400
    except Exception as e:
        logging.error(f"Error deleting card '{card_id}': {e}", exc_info=True)
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
    logging.info(f"Received request to delete column_id: {column_id}")

    if columns_collection is None or tasks_collection is None:
        logging.error(f"Cannot delete column '{column_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    # Prevent deletion of default columns? (Optional business logic)
    # try:
    #     column_doc = columns_collection.find_one({'_id': ObjectId(column_id)})
    #     if column_doc and column_doc['name'] in ['Back Log', 'In Progress', 'Done'] and column_doc['board_id'] == 'default_board':
    #         logging.warning(f"Attempted to delete a default column '{column_id}' ('{column_doc['name']}'). Aborting.")
    #         return jsonify({'success': False, 'error': 'Cannot delete default columns'}), 403 # Forbidden
    # except bson.errors.InvalidId:
    #      logging.error(f"Column deletion check failed: Invalid column_id format '{column_id}'.")
    #      return jsonify({'success': False, 'error': 'Invalid column ID format'}), 400
    # except Exception as e:
    #      logging.error(f"Error checking if column '{column_id}' is deletable: {e}", exc_info=True)
    #      return jsonify({'success': False, 'error': f'Failed to check column: {e}'}), 500


    try:
        # Check if column exists before attempting to delete tasks
        column_delete_result = columns_collection.find_one({'_id': ObjectId(column_id)})
        if not column_delete_result:
             logging.warning(f"Column deletion failed: Column with ID '{column_id}' not found.")
             return jsonify({'success': False, 'error': 'Column not found'}), 404

        # Delete all cards associated with the column
        # Use the validated ObjectId string
        task_delete_result = tasks_collection.delete_many({'column_id': column_id})
        logging.info(f"Deleted {task_delete_result.deleted_count} tasks associated with column '{column_id}'.")

        # Delete the column itself using the validated ObjectId
        result = columns_collection.delete_one({'_id': ObjectId(column_id)})

        # This check should be redundant due to find_one above, but good practice
        if result.deleted_count > 0:
            logging.info(f"Successfully deleted column '{column_id}'.")
            # Consider re-ordering remaining columns if necessary (more complex)
            return jsonify({'success': True, 'message': 'Column and associated cards deleted'})
        else:
             # This case should ideally not be reached if find_one succeeded
             logging.error(f"Column deletion consistency issue: Column '{column_id}' found but delete_one reported 0 deleted.")
             return jsonify({'success': False, 'error': 'Column found but could not be deleted'}), 500

    # Specific exception for invalid ObjectId format
    except bson.errors.InvalidId:
         logging.error(f"Column deletion failed: Invalid column_id format '{column_id}'.")
         return jsonify({'success': False, 'error': 'Invalid column ID format'}), 400
    except Exception as e:
        logging.error(f"Error deleting column '{column_id}': {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Failed to delete column: {e}'}), 500


@app.route('/api/columns/<string:column_id>/move', methods=['POST'])
def move_column(column_id):
    """
    Move a column to a new position in the board.

    Expects 'new_order' in form data.

    Args:
        column_id (str): The ID of the column to move.

    Returns:
        jsonify: A JSON response indicating success or failure.
    """
    logging.info(f"Received request to move column_id: {column_id}")

    if columns_collection is None:
        logging.error(f"Cannot move column '{column_id}': Database connection failed.")
        return jsonify({'error': 'Database connection failed'}), 500

    new_order_str = request.form.get('new_order')
    if new_order_str is None:
        logging.warning(f"Column move failed for column '{column_id}': new_order is required.")
        return jsonify({'success': False, 'error': 'New order is required'}), 400

    try:
        new_order = int(new_order_str)
    except ValueError:
        logging.warning(f"Column move failed for column '{column_id}': Invalid new_order value '{new_order_str}'.")
        return jsonify({'success': False, 'error': 'Invalid new order value, must be an integer.'}), 400

    try:
        # Fetch the column to validate its existence
        column = columns_collection.find_one({'_id': ObjectId(column_id)})
        if not column:
            logging.error(f"Column move failed: Column with ID '{column_id}' not found.")
            return jsonify({'success': False, 'error': 'Column not found'}), 404

        board_id = column['board_id']

        # Update the order of other columns in the same board
        columns = list(columns_collection.find({'board_id': board_id}).sort('order'))
        for col in columns:
            if col['_id'] == ObjectId(column_id):
                continue
            if col['order'] >= new_order:
                columns_collection.update_one({'_id': col['_id']}, {'$inc': {'order': 1}})

        # Update the order of the target column
        result = columns_collection.update_one(
            {'_id': ObjectId(column_id)},
            {'$set': {'order': new_order}}
        )

        if result.modified_count > 0:
            logging.info(f"Successfully moved column '{column_id}' to order {new_order}.")
            return jsonify({'success': True, 'message': 'Column moved successfully'})
        else:
            logging.info(f"Column '{column_id}' was matched but not modified (already in target state?).")
            return jsonify({'success': True, 'message': 'Column already in target state'})

    except bson.errors.InvalidId:
        logging.error(f"Column move failed: Invalid column_id format '{column_id}'.")
        return jsonify({'success': False, 'error': 'Invalid column ID format'}), 400
    except Exception as e:
        logging.error(f"Error moving column '{column_id}': {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Failed to move column: {e}'}), 500

# Make sure to import bson near the top if using bson.errors.InvalidId
import bson.errors

if __name__ == '__main__':
    # Ensure .env exists or create a default one
    if not os.path.exists('.env'):
        try:
            with open('.env', 'w') as f:
                f.write("# Default MongoDB connection settings\n")
                f.write("MONGO_URI=mongodb://localhost:27017/\n")
                f.write("MONGO_DATABASE=todo\n")
            print("Created a default .env file. Please review and adjust MongoDB connection details if necessary.")
        except IOError as e:
            print(f"Warning: Could not create default .env file: {e}")

    # Start the Flask application
    # Use host='0.0.0.0' to make it accessible on your network, useful for testing from other devices
    # debug=True automatically reloads on code changes but SHOULD NOT be used in production
    logging.info("Flask application starting...")
    app.run(host='0.0.0.0', port=5000, debug=True)