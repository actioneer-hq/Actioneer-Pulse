import { ToastProvider, TooltipProvider } from "@actioneer/ads";
import { MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ActiveAgentProvider } from "./ActiveAgentProvider";
import App from "./App";
import { AuthProvider } from "./auth";
import { BackfillProvider } from "./BackfillProvider";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* ADS providers wrap everything once: reduced-motion honoured, toasts + tooltips available. */}
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <TooltipProvider>
          <BrowserRouter>
            <AuthProvider>
              <ActiveAgentProvider>
                <BackfillProvider>
                  <App />
                </BackfillProvider>
              </ActiveAgentProvider>
            </AuthProvider>
          </BrowserRouter>
        </TooltipProvider>
      </ToastProvider>
    </MotionConfig>
  </StrictMode>,
);
