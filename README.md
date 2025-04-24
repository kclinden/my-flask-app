# my-flask-app
This is a basic kanban flask app that can be tested locally or deployed into AWS. It is intententionally insecure for use with Wiz Code.

## Run Database to Test
```
docker run -d \
    --name my-mongo-test \
    -p 27017:27017 \
    -v "$(pwd)/init-mongo.sh:/docker-entrypoint-initdb.d/init-mongo.sh:ro" \
    -e MONGO_INIT_HOST=localhost \
    -e MONGO_INIT_PORT=27017 \
    -e MONGO_INIT_DATABASE=todo \
    -e MONGO_INIT_USERNAME=myuser \
    -e MONGO_INIT_PASSWORD=mypassword \
    mongo
```

## Run App to Test
```
export FLASK_APP=todo_app/app.py
export MONGO_URI="mongodb://myuser:mypassword@localhost:27017/todo?authSource=todo"
export MONGO_DATABASE="todo"
flask run --debug
```