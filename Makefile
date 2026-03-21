.PHONY: install demo lint clean help

help:
	@echo "k8s-cost-radar Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make install    - Install Python dependencies"
	@echo "  make demo       - Run in demo mode with mock data"
	@echo "  make lint       - Run code linting (requires flake8, pylint)"
	@echo "  make clean      - Remove Python artifacts"
	@echo "  make help       - Show this help message"

install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt
	@echo "✓ Installation complete!"
	@echo ""
	@echo "Try it out:"
	@echo "  make demo                    # Demo with mock data"
	@echo "  python k8s_cost_radar.py scan  # Scan your cluster"

demo:
	@echo "Running k8s-cost-radar in DEMO mode..."
	@echo ""
	python k8s_cost_radar.py demo

lint:
	@echo "Running linting..."
	@echo ""
	@which flake8 > /dev/null 2>&1 || (echo "flake8 not found. Install with: pip install flake8" && exit 1)
	flake8 k8s_cost_radar.py --max-line-length=120 --ignore=E501,W503
	@echo ""
	@which pylint > /dev/null 2>&1 || (echo "pylint not found. Install with: pip install pylint" && exit 1)
	pylint k8s_cost_radar.py --max-line-length=120 --disable=C0103,C0114,C0115,C0116,R0913,R0914,R0915
	@echo "✓ Linting complete!"

clean:
	@echo "Cleaning Python artifacts..."
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -delete
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '.coverage' -delete
	find . -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleanup complete!"
