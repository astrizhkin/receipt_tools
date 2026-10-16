"""Entry point: uvicorn phunter.api:app on 0.0.0.0:8000."""
import logging

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run("phunter.api:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
