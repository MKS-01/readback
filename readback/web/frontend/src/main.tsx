import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// Single theme (Ghost). Without this the CSS falls back to the :root palette
// where --accent is undefined and the decorative HUD rings aren't hidden.
document.body.classList.add("theme-ghost");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
