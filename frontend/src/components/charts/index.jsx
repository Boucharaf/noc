import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";
import { Bar, Line } from "react-chartjs-2";

import { useChartTheme } from "./useChartTheme";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Filler,
  Tooltip,
  Legend,
);

function baseOptions(chrome, { legend = false, yTitle, xTicks = 8, stacked = false } = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 180 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: legend
        ? {
            display: true,
            position: "bottom",
            labels: {
              color: chrome.inkMuted,
              boxWidth: 8,
              boxHeight: 8,
              usePointStyle: true,
              font: { size: 11 },
            },
          }
        : { display: false },
      tooltip: {
        backgroundColor: chrome.surface,
        borderColor: chrome.border,
        borderWidth: 1,
        titleColor: chrome.ink,
        bodyColor: chrome.ink,
        padding: 8,
        cornerRadius: 3,
        displayColors: true,
        boxWidth: 8,
        boxHeight: 8,
        usePointStyle: true,
        titleFont: { size: 11, weight: "600" },
        bodyFont: { size: 11, family: "ui-monospace, monospace" },
      },
    },
    scales: {
      x: {
        stacked,
        grid: { display: false },
        border: { display: false },
        ticks: {
          color: chrome.inkMuted,
          font: { size: 10 },
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: xTicks,
        },
      },
      y: {
        stacked,
        beginAtZero: true,
        grid: { color: chrome.grid, drawTicks: false },
        border: { display: false },
        title: yTitle
          ? { display: true, text: yTitle, color: chrome.inkMuted, font: { size: 10 } }
          : undefined,
        ticks: {
          color: chrome.inkMuted,
          font: { size: 10, family: "ui-monospace, monospace" },
          maxTicksLimit: 5,
          padding: 4,
        },
      },
    },
  };
}

/**
 * Courbe.
 *
 * `series` : [{ label, data:number[], color, fill?, dashed? }]
 * `bands`  : bandes min/max facultatives, dessinées en aire translucide
 *            sous la courbe — indispensable sur un agrégat réseau, où la
 *            moyenne seule masque qu'un site est à 100 % et un autre à 0.
 */
export function LineChart({
  labels,
  series,
  height = 180,
  legend,
  yTitle,
  yMax,
  yMin,
  valueFormatter,
  targetLine,
}) {
  const chrome = useChartTheme();

  const data = {
    labels,
    datasets: series.map((s) => ({
      label: s.label,
      data: s.data,
      borderColor: s.color,
      backgroundColor: s.fill
        ? `color-mix(in srgb, ${s.color} 18%, transparent)`
        : s.color,
      borderWidth: s.width ?? 1.6,
      borderDash: s.dashed ? [4, 3] : undefined,
      fill: s.fill ?? false,
      tension: 0.25,
      pointRadius: 0,
      pointHoverRadius: 3,
      pointHitRadius: 12,
      spanGaps: true,
    })),
  };

  const options = baseOptions(chrome, {
    legend: legend ?? series.length > 1,
    yTitle,
  });
  options.scales.y.max = yMax;
  options.scales.y.min = yMin;
  if (valueFormatter) {
    options.plugins.tooltip.callbacks = {
      label: (context) => `${context.dataset.label} : ${valueFormatter(context.parsed.y)}`,
    };
    options.scales.y.ticks.callback = (value) => valueFormatter(value);
  }

  // Ligne d'objectif : tracée comme une série constante plutôt qu'avec un
  // plugin d'annotation, pour ne pas ajouter une dépendance de plus.
  if (targetLine !== undefined && targetLine !== null) {
    data.datasets.push({
      label: "Objectif",
      data: labels.map(() => targetLine),
      borderColor: chrome.inkMuted,
      borderWidth: 1,
      borderDash: [3, 3],
      pointRadius: 0,
      fill: false,
    });
  }

  return (
    <div style={{ height }}>
      <Line data={data} options={options} />
    </div>
  );
}

/** Histogramme — répartition horaire, comparaison mensuelle, causes. */
export function BarChart({
  labels,
  series,
  height = 180,
  horizontal = false,
  stacked = false,
  legend,
  valueFormatter,
}) {
  const chrome = useChartTheme();

  const data = {
    labels,
    datasets: series.map((s) => ({
      label: s.label,
      data: s.data,
      backgroundColor: s.colors ?? s.color,
      borderRadius: 2,
      borderSkipped: false,
      barPercentage: 0.82,
      categoryPercentage: 0.82,
    })),
  };

  const options = baseOptions(chrome, {
    legend: legend ?? series.length > 1,
    stacked,
    xTicks: horizontal ? 5 : 12,
  });
  options.indexAxis = horizontal ? "y" : "x";
  if (horizontal) {
    options.scales.x.grid = { color: chrome.grid, drawTicks: false };
    options.scales.y.grid = { display: false };
    options.scales.y.ticks.maxTicksLimit = 20;
  }
  if (valueFormatter) {
    options.plugins.tooltip.callbacks = {
      label: (context) =>
        `${context.dataset.label} : ${valueFormatter(horizontal ? context.parsed.x : context.parsed.y)}`,
    };
  }

  return (
    <div style={{ height }}>
      <Bar data={data} options={options} />
    </div>
  );
}

/**
 * Sparkline en SVG pur.
 *
 * Pas de Chart.js ici : une sparkline vit dans une cellule de tableau et
 * il peut y en avoir cinquante à l'écran. Cinquante canvas Chart.js, ce
 * sont cinquante contextes de rendu et une page qui rame ; cinquante
 * `<path>` ne coûtent rien.
 */
export function Sparkline({ values, color = "var(--accent)", width = 80, height = 20, fill = true }) {
  const points = (values ?? []).filter((v) => v !== null && v !== undefined);
  if (points.length < 2) {
    return (
      <span className="text-[10px]" style={{ color: "var(--ink-3)" }}>
        —
      </span>
    );
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  // Série plate : sans ce garde-fou, (max - min) vaut 0 et la ligne part
  // à l'infini.
  const span = max - min || 1;
  const step = width / (points.length - 1);

  const coords = points.map((value, index) => [
    index * step,
    height - ((value - min) / span) * (height - 2) - 1,
  ]);
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;

  return (
    <svg width={width} height={height} style={{ display: "block", overflow: "visible" }} aria-hidden="true">
      {fill && <path d={area} fill={color} opacity="0.13" />}
      <path d={line} fill="none" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Carte de chaleur horaire (24 colonnes).
 *
 * Répond au besoin métier « à quelle heure tombent les pannes » — et,
 * indirectement, au dimensionnement des équipes de nuit. Une courbe sur
 * 24 points le dirait aussi, mais la bande de couleur se lit d'un coup
 * d'œil sans axe à décoder.
 */
export function HourHeatmap({ data, color = "var(--sev-high)", height = 34 }) {
  const byHour = new Map((data ?? []).map((row) => [row.hour, row.total_incidents]));
  const values = Array.from({ length: 24 }, (_, hour) => byHour.get(hour) ?? 0);
  const max = Math.max(...values, 1);

  return (
    <div>
      <div className="flex gap-[2px]" style={{ height }}>
        {values.map((value, hour) => (
          <div
            key={hour}
            className="flex-1 rounded-[2px]"
            title={`${String(hour).padStart(2, "0")} h — ${value} incident${value > 1 ? "s" : ""}`}
            style={{
              background:
                value === 0
                  ? "var(--surface-3)"
                  : `color-mix(in srgb, ${color} ${Math.round(18 + (value / max) * 82)}%, transparent)`,
            }}
          />
        ))}
      </div>
      <div className="flex justify-between mt-1 text-[9.5px] num" style={{ color: "var(--ink-3)" }}>
        <span>00 h</span>
        <span>06 h</span>
        <span>12 h</span>
        <span>18 h</span>
        <span>23 h</span>
      </div>
    </div>
  );
}

/**
 * Anneau de répartition, en SVG.
 *
 * Chart.js sait le faire ; on s'en passe pour garder la maîtrise du trou
 * central, où l'on affiche le total — c'est cette valeur que l'œil
 * cherche en premier, pas la proportion des tranches.
 */
export function Donut({ segments, size = 116, thickness = 13, centerValue, centerLabel }) {
  const total = segments.reduce((sum, segment) => sum + (segment.value || 0), 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--surface-3)"
          strokeWidth={thickness}
        />
        {total > 0 &&
          segments.map((segment) => {
            const fraction = (segment.value || 0) / total;
            const dash = fraction * circumference;
            const element = (
              <circle
                key={segment.key}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={segment.color}
                strokeWidth={thickness}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-offset}
              >
                <title>{`${segment.label} : ${segment.value}`}</title>
              </circle>
            );
            offset += dash;
            return element;
          })}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span className="num font-semibold" style={{ fontSize: 19 }}>
          {centerValue}
        </span>
        {centerLabel && (
          <span className="text-[9.5px] uppercase tracking-[0.06em]" style={{ color: "var(--ink-3)" }}>
            {centerLabel}
          </span>
        )}
      </div>
    </div>
  );
}
