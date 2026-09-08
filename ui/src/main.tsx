import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import { BackfillProvider } from "./BackfillProvider";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <BackfillProvider>
          <App />
        </BackfillProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
