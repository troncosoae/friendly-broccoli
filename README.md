# friendly-broccoli

Team admin platform.

## Run locally

### List of mapped ports used per service

- team_members: 8000
- ball_collectors: 8001

### Using Docker Compose

```bash
docker compose up --build
```

### Starting each service independently

1. Start the network.

    ```bash
    sudo docker network create app_network
    ```

2. Build the `team_members` service.

    ```bash
    sudo docker build -t team_members_service services/team_members
    ```

3. Start the service.

    ```bash
    sudo docker run --rm -d --name team_members_api --network app_network -p 8000:80 team_members_service
    ```

## Deploy

### Upload a docker image of a service to gcp

```bash
gcloud builds submit --tag <artifact_registry_repo_path>/team-members-service
```

### Run the docker image

```bash
gcloud run deploy team-members-service \
  --image <artifact_registry_repo_path>/team-members-service \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 80 \
  --set-env-vars MONGODB_URI=<YOUR_MONGODB_URI>,DB_NAME=<YOUR_DB_NAME>
```
