import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

const storedTheme = localStorage.getItem("theme");
const initialTheme = storedTheme === "light" || storedTheme === "dark" ? storedTheme : "dark";
document.documentElement.dataset.theme = initialTheme;

const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>
);
