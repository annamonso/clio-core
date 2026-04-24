/*
 * Copyright (c) 2026, Gnosis Research Center, Illinois Institute of Technology
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <mchips/client/mcp_client.h>
#include <mchips/protocol/mcp_types.h>

#include <mchips/protocol/json_rpc.h>
namespace nb = nanobind;
using namespace mchips::client;
using namespace mchips::protocol;

NB_MODULE(mchips_ext, m) {
  m.doc() = "MChiPs MCP Client — Python bindings for the standalone C++ client";

  // ── ToolAnnotations ──────────────────────────────────────────────────────
  nb::class_<ToolAnnotations>(m, "ToolAnnotations",
      "Hints to the MCP client about tool behavior and placement")
    .def(nb::init<>())
    .def_rw("read_only_hint",  &ToolAnnotations::readOnlyHint,
            "True if the tool does not modify external state")
    .def_rw("destructive_hint", &ToolAnnotations::destructiveHint,
            "True if the tool may destroy data")
    .def_rw("idempotent_hint", &ToolAnnotations::idempotentHint,
            "True if repeating the same call is safe")
    .def_rw("priority",        &ToolAnnotations::priority,
            "Storage tier hint: 1.0=RAM, 0.5=SSD, 0.0=archive");

  // ── ToolDefinition ───────────────────────────────────────────────────────
  nb::class_<ToolDefinition>(m, "ToolDefinition",
      "MCP tool descriptor: name, description, and JSON Schema input spec")
    .def(nb::init<>())
    .def_ro("name",        &ToolDefinition::name,        "Tool name (e.g., 'cte__put_blob')")
    .def_ro("description", &ToolDefinition::description, "Human-readable description")
    .def("__repr__", [](const ToolDefinition& td) {
      return "<ToolDefinition name='" + td.name + "'>";
    });

  // ── ContentItem ──────────────────────────────────────────────────────────
  nb::class_<ContentItem>(m, "ContentItem",
      "A single content block in a tool call result")
    .def(nb::init<>())
    .def_ro("type", &ContentItem::type, "Content type ('text', 'image', etc.)")
    .def("text", [](const ContentItem& ci) -> std::string {
      return ci.text.value_or("");
    }, "Text content (empty string if not a text item)")
    .def("__repr__", [](const ContentItem& ci) {
      return "<ContentItem type='" + ci.type + "'>";
    });

  // ── CallToolResult ───────────────────────────────────────────────────────
  nb::class_<CallToolResult>(m, "CallToolResult",
      "Result returned from a tools/call request")
    .def(nb::init<>())
    .def_ro("content",  &CallToolResult::content,  "List of ContentItem objects")
    .def_ro("is_error", &CallToolResult::isError,  "True if the tool call failed")
    .def("text", [](const CallToolResult& r) -> std::string {
      // Concatenate all text items for convenience
      std::string out;
      for (const auto& c : r.content) {
        if (c.text.has_value()) {
          if (!out.empty()) out += "\n";
          out += *c.text;
        }
      }
      return out;
    }, "Convenience accessor: all text content joined with newlines")
    .def("__repr__", [](const CallToolResult& r) {
      return std::string("<CallToolResult is_error=") +
             (r.isError ? "True" : "False") + ">";
    });

  // ── McpClient ────────────────────────────────────────────────────────────
  nb::class_<McpClient>(m, "McpClient",
      "Standalone MCP client using Streamable HTTP transport.\n\n"
      "Connects to an MChiPs gateway (or any MCP-compliant server) and\n"
      "provides initialize/list_tools/call_tool/close methods.\n\n"
      "Example::\n\n"
      "    import mchips_ext\n"
      "    c = mchips_ext.McpClient('http://localhost:8080/mcp')\n"
      "    c.initialize()\n"
      "    tools = c.list_tools()\n"
      "    result = c.call_tool('cte__put_blob',\n"
      "                         {'tag_name': 't', 'blob_name': 'b',\n"
      "                          'data': 'SGVsbG8='})\n"
      "    c.close()")
    .def("__init__", [](McpClient* self, const std::string& url) {
           new (self) McpClient(McpClientConfig{url});
         }, nb::arg("url"),
         "Create a client for the given MCP endpoint URL.\n\n"
         "The URL should be the full endpoint, e.g.:\n"
         "  'http://localhost:8080/mcp'\n"
         "No connection is made until initialize() is called.")
    .def("initialize", &McpClient::Initialize,
         "Send the MCP initialize handshake.\n\n"
         "Must be called before list_tools() or call_tool().\n"
         "Raises std::runtime_error on transport failure.")
    .def("list_tools", &McpClient::ListTools,
         "Return all tools advertised by the server.\n\n"
         "Returns a list of ToolDefinition objects.\n"
         "Raises std::runtime_error if not initialized.")
    .def("call_tool", [](McpClient& self,
                         const std::string& name,
                         nb::dict py_args) -> CallToolResult {
           // Convert Python dict → nlohmann json
           json args = json::object();
           for (auto [k, v] : py_args) {
             std::string key = nb::cast<std::string>(k);
             // Support str/int/float/bool values from Python
             if (nb::isinstance<nb::str>(v)) {
               args[key] = nb::cast<std::string>(v);
             } else if (nb::isinstance<nb::bool_>(v)) {
               args[key] = nb::cast<bool>(v);
             } else if (nb::isinstance<nb::int_>(v)) {
               args[key] = nb::cast<int64_t>(v);
             } else if (nb::isinstance<nb::float_>(v)) {
               args[key] = nb::cast<double>(v);
             } else {
               args[key] = nb::cast<std::string>(nb::str(v));
             }
           }
           return self.CallTool(name, args);
         },
         nb::arg("name"), nb::arg("args"),
         "Call a tool by name with the given arguments dict.\n\n"
         "Parameters:\n"
         "  name: Qualified tool name (e.g., 'cte__put_blob')\n"
         "  args: Dict of tool arguments\n\n"
         "Returns a CallToolResult.\n"
         "Raises std::runtime_error if not initialized.")
    .def("close", &McpClient::Close,
         "Close the MCP session and release the HTTP connection.")
    .def("is_initialized", &McpClient::IsInitialized,
         "Return True if the session is active.");
}
