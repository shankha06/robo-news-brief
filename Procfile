web: gunicorn app:app --worker-class uvicorn.workers.UvicornWorker --workers 1 --preload --bind 0.0.0.0:$PORT --timeout 120 --max-requests 400 --max-requests-jitter 50
