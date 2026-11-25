import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { registerSW } from "virtual:pwa-register";

import App from "./App.jsx";
// Polices de la maquette ANPTIC (AM-06) : Poppins pour les titres et les
// chiffres clés, IBM Plex Sans pour le texte. Servies par l'application
// elle-même (sous-ensemble latin) : le CSP n'autorise que font-src 'self',
// et un poste de la salle NOC peut n'avoir aucun accès à Internet.
import "@fontsource/poppins/latin-500.css";
import "@fontsource/poppins/latin-600.css";
import "@fontsource/poppins/latin-700.css";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "./index.css";
import "leaflet/dist/leaflet.css";

registerSW({ immediate: true });

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Les intervalles de rafraîchissement sont décidés requête par
      // requête dans hooks/queries.js (LIVE / OPERATIONAL / ANALYTIC) :
      // ce défaut ne sert qu'aux requêtes qui n'en déclarent pas.
      staleTime: 30_000,
      // Un poste de supervision reste ouvert des heures et l'opérateur
      // passe sans cesse d'une fenêtre à l'autre : refetch à chaque
      // reprise de focus provoquerait une rafale de requêtes sans apport,
      // le polling programmé suffit.
      refetchOnWindowFocus: false,
      // Une erreur réseau passagère ne doit pas vider un écran ; deux
      // tentatives suffisent, au-delà c'est une vraie panne qu'il faut
      // afficher plutôt que masquer.
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
    mutations: {
      // Une action d'exploitation (acquitter, résoudre) ne se rejoue
      // JAMAIS toute seule : un double acquittement fausserait le MTTA.
      retry: 0,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
