import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
import App from "./App";
import { RuntimeProvider } from "./lib/useRuntime";
import "./index.css";

// R10: LazyMotion подгружает только DOM-анимации (меньше бандл); при
// prefers-reduced-motion: reduce MotionConfig отключает смещения/масштабы.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <RuntimeProvider>
        <MotionConfig reducedMotion="user">
          <LazyMotion features={domAnimation} strict>
            <App />
          </LazyMotion>
        </MotionConfig>
      </RuntimeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
