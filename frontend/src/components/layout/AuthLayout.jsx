/**
 * Fond des écrans publics (connexion, mot de passe oublié, nouveau mot de
 * passe) : carte du Burkina floutée, dégradé bleu, logo. Toujours en clair.
 */
export default function AuthLayout({ children }) {
  return (
    <div
      style={{
        position: "relative",
        minHeight: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px 16px",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: "url(/carte_du_BF.jpg)",
          backgroundSize: "cover",
          backgroundPosition: "center",
          filter: "blur(5px)",
          transform: "scale(1.06)", /* évite les bords blancs du flou */
          zIndex: 0,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(to bottom, rgba(20, 60, 120, 0.38) 0%, rgba(10, 35, 90, 0.72) 100%)",
          zIndex: 1,
        }}
      />
      <div className="light" style={{ position: "relative", zIndex: 2, width: "100%", maxWidth: 380 }}>
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          <img
            src="/images.png"
            alt="ANPTIC"
            style={{
              height: 56,
              width: "auto",
              objectFit: "contain",
              display: "inline-block",
              filter: "drop-shadow(0 2px 8px rgba(0,0,0,0.4))",
            }}
          />
        </div>
        <div
          style={{
            background: "rgba(245, 247, 249, 0.97)",
            borderRadius: 12,
            boxShadow: "0 8px 40px rgba(10, 35, 90, 0.28), 0 2px 8px rgba(0,0,0,0.12)",
            overflow: "hidden",
            border: "1px solid rgba(34, 101, 172, 0.15)",
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
