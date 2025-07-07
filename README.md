# friendly-broccoli

Team admin platform.

## Run locally

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
