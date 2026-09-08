import { Component } from "react";
import { AlertOctagon } from "lucide-react";

/**
 * Frontière d'erreur.
 *
 * Sans elle, une seule exception pendant le rendu d'un composant vide
 * TOUT le document : React démonte l'arbre entier et laisse une page
 * blanche, sans le moindre message. Sur une console de supervision c'est
 * le pire échec possible — l'écran mural devient noir et personne ne sait
 * si le réseau va bien ou si l'interface est morte.
 *
 * Posée autour du contenu de page, elle transforme ce scénario en un
 * panneau lisible : la barre d'état, le ticker d'alertes et la navigation
 * restent en place, et l'exploitant peut changer d'écran.
 *
 * `resetKey` (la route courante) remonte la frontière à chaque navigation :
 * sinon, une fois l'erreur affichée, elle resterait affichée même après
 * avoir changé de page.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, resetKey: props.resetKey };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  /**
   * La remise à zéro se fait ici et non dans `componentDidUpdate` : ce
   * dernier imposerait un `setState` après coup, donc un second rendu à
   * chaque navigation. Ici l'état est corrigé pendant le rendu courant.
   */
  static getDerivedStateFromProps(props, state) {
    if (props.resetKey === state.resetKey) return null;
    return { error: null, resetKey: props.resetKey };
  }

  componentDidCatch(error, info) {
    // Conservé dans la console du navigateur : c'est la seule trace
    // exploitable pour reproduire, l'interface n'expose pas la pile.
    console.error("[NOC] Erreur de rendu :", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="panel p-4 m-2" style={{ borderColor: "var(--sev-critical)" }}>
        <div className="flex items-start gap-3">
          <AlertOctagon size={20} style={{ color: "var(--sev-critical)" }} />
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold" style={{ color: "var(--sev-critical)" }}>
              Cet écran n'a pas pu s'afficher
            </h2>
            <p className="text-[12.5px] mt-1" style={{ color: "var(--ink-2)" }}>
              Le reste de l'application continue de fonctionner : les compteurs d'alerte
              en haut de page restent à jour, et les autres écrans sont accessibles.
            </p>
            <p className="mono-xs mt-2" style={{ color: "var(--ink-3)" }}>
              {String(this.state.error?.message || this.state.error).slice(0, 300)}
            </p>
            <div className="flex gap-2 mt-3">
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => this.setState({ error: null })}
              >
                Réessayer
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => window.location.reload()}
              >
                Recharger la page
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
