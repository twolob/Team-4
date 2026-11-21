# AgTrack Frontend

The React and TypeScript application lives here. The FastAPI service in the sibling backend directory owns authentication, farm records, and the public batch lookup. The Lovable builder provides the design reference, and the AgTrack Lovable build prompt describes the intended application workflows.

## Local development

Follow the [backend setup](../backend/README.md) to start FastAPI on port 8000. Configure the frontend with `VITE_API_BASE_URL=http://localhost:8000` in `.env.local`. FastAPI's `FRONTEND_HOST` must match the Vite origin, usually `http://localhost:5173`.

```powershell
npm install
npm run dev
```

Open <http://localhost:5173/>. The public page links to farmer registration and sign-in. Buyers can look up a batch code created by the backend's traceability API. Signed-in users open the farm overview at `/dashboard`.

`npm run build` type-checks and builds the frontend. For a separate frontend deployment, serve the Vite output with an SPA fallback and set `VITE_API_BASE_URL` before building.

## Generate Client

### Automatically

- From the project root, run the script:

```bash
bash ./scripts/generate-client.sh
```

- Commit the changes.

### Manually

- Make sure the backend is running.

- Download the OpenAPI JSON file from `http://localhost:8000/api/v1/openapi.json` and copy it to a new file `openapi.json` at the root of the `frontend` directory.

- To generate the frontend client, run:

```bash
bun run generate-client
```

- Commit the changes.

Regenerate the client whenever backend changes affect the OpenAPI schema.

## Using a Remote API

By default, the built frontend uses the same origin as the FastAPI app. If you want to use a remote API while running the Vite development server, you can set the environment variable `VITE_API_URL` to the URL of the remote API. For example, you can set it in the `frontend/.env` file:

```env
VITE_API_URL=https://my-domain.example.com
```

Then, when you run the frontend, it will use that URL as the base URL for the API.

## Code Structure

The frontend code is structured as follows:

- `frontend/src` - The main frontend code.
- `frontend/public` - Static assets.
- `frontend/src/client` - The generated OpenAPI client.
- `frontend/src/components` - The components of the frontend, including the shadcn/ui components in `frontend/src/components/ui`.
- `frontend/src/hooks` - Custom hooks.
- `frontend/src/lib` - Shared frontend utilities.
- `frontend/src/routes` - The frontend routes and pages.

## End-to-End Testing with Playwright

The frontend includes initial end-to-end tests using Playwright. To run the tests, you need to have the Docker Compose stack running. Start the stack with the following command:

```bash
docker compose run --rm backend bash scripts/prestart.sh
docker compose up -d --wait backend
```

Then, you can run the tests with the following command:

```bash
bunx playwright test
```

You can also run your tests in UI mode to see the browser and interact with it running:

```bash
bunx playwright test --ui
```

To stop and remove the Docker Compose stack and clean the data created in tests, use the following command:

```bash
docker compose down -v
```

To update the tests, navigate to the tests directory and modify the existing test files or add new ones as needed.

For more information on writing and running Playwright tests, refer to the official [Playwright documentation](https://playwright.dev/docs/intro).
