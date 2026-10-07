import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { RuntimeProvider } from "./lib/useRuntime";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <RuntimeProvider>
        <App />
      </RuntimeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
