# context-visualizer build helpers.
#
# The Python package is pip-installable as-is — you only need this Makefile
# when you're touching the multi-agent workspace React app under frontend/.
#
# Targets:
#   workspace         Install JS deps and build the SPA into
#                     context_visualizer/static/workspace/. This is what
#                     Flask serves at /workspace. Run this before packaging
#                     a release or after pulling a branch that changed
#                     frontend/ sources.
#   workspace-dev     Launch the Vite dev server on :5173 with /api and
#                     /_interceptor proxied to a local Flask on :5000.
#                     Use this while iterating on the workspace UI.
#   workspace-clean   Wipe the built SPA bundle.
#
# The frontend is intentionally not wired into the root CMake build; UI
# iteration doesn't need a C++ rebuild cycle, and release packaging picks
# up the built bundle from static/workspace/ via pyproject package-data.

FRONTEND_DIR := frontend
BUNDLE_DIR   := context_visualizer/static/workspace

.PHONY: workspace workspace-dev workspace-clean

workspace:
	cd $(FRONTEND_DIR) && npm install && npm run build

workspace-dev:
	cd $(FRONTEND_DIR) && npm install && npm run dev

workspace-clean:
	rm -rf $(BUNDLE_DIR)
