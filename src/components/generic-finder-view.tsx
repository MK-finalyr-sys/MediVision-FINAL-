"use client";
import { useState, useEffect } from "react";
import {
  Coins,
  Search,
  Pill,
  ArrowRight,
  TrendingDown,
  Building2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  ShieldCheck,
  LoaderCircle,
  Sparkles,
  X,
  Stethoscope,
} from "lucide-react";
import { medicines } from "@/lib/catalog";
import type { Medicine } from "@/lib/contracts";
import { aiPricing, type PricingResult } from "@/lib/ai-backend";

interface GenericFinderProps {
  initialMedicine?: Medicine | null;
  onOpenMedicine?: (m: Medicine) => void;
  onNavigateSafety?: (medicine: Medicine | string) => void;
  onNavigateChat?: (medicine: Medicine | string) => void;
}

const COMMON_SEARCH_SUGGESTIONS = [
  { brand: "Dolo 650", salt: "Paracetamol", strength: "650 mg" },
  { brand: "Augmentin 625", salt: "Amoxicillin and Clavulanic Acid", strength: "625 mg" },
  { brand: "Glycomet 500", salt: "Metformin", strength: "500 mg" },
  { brand: "Atorva 10", salt: "Atorvastatin", strength: "10 mg" },
  { brand: "Pantocid 40", salt: "Pantoprazole", strength: "40 mg" },
  { brand: "Azithral 500", salt: "Azithromycin", strength: "500 mg" },
  { brand: "Telma 40", salt: "Telmisartan", strength: "40 mg" },
];

export function GenericFinderView({
  initialMedicine,
  onOpenMedicine,
  onNavigateSafety,
  onNavigateChat,
}: GenericFinderProps) {
  const [searchTerm, setSearchTerm] = useState(
    initialMedicine?.name || initialMedicine?.activeIngredient || ""
  );
  const [selectedSalt, setSelectedSalt] = useState(
    initialMedicine?.activeIngredient || ""
  );
  const [strength, setStrength] = useState(initialMedicine?.strength || "");
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [result, setResult] = useState<PricingResult | null>(null);
  const [offlineError, setOfflineError] = useState(false);

  useEffect(() => {
    if (!initialMedicine?.activeIngredient) return;
    let ignore = false;
    aiPricing(initialMedicine.activeIngredient, initialMedicine.strength || undefined)
      .then((res) => {
        if (ignore) return;
        setResult(res);
        setHasSearched(true);
        if (!res || res.available === false || !res.ok) {
          setOfflineError(true);
        }
      })
      .catch(() => {
        if (!ignore) setOfflineError(true);
      });
    return () => {
      ignore = true;
    };
  }, [initialMedicine]);

  async function executePricingLookup(salt: string, str?: string) {
    const cleanSalt = salt.trim();
    if (!cleanSalt) return;

    setLoading(true);
    setHasSearched(true);
    setOfflineError(false);
    setResult(null);

    try {
      const res = await aiPricing(cleanSalt, str?.trim() || undefined);
      if (!res || res.available === false || !res.ok) {
        setOfflineError(true);
        setResult(res);
      } else {
        setResult(res);
      }
    } catch {
      setOfflineError(true);
    } finally {
      setLoading(false);
    }
  }

  function handleSearchSubmit(e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!searchTerm.trim()) return;

    // Check if the query matches a catalog medicine brand/name
    const foundInCatalog = medicines.find(
      (m) =>
        m.name.toLowerCase() === searchTerm.toLowerCase() ||
        m.activeIngredient.toLowerCase() === searchTerm.toLowerCase() ||
        m.aliases.some((a) => a.toLowerCase().includes(searchTerm.toLowerCase()))
    );

    const saltToUse = foundInCatalog ? foundInCatalog.activeIngredient : searchTerm.trim();
    const strengthToUse = strength || (foundInCatalog ? foundInCatalog.strength : undefined);

    setSelectedSalt(saltToUse);
    void executePricingLookup(saltToUse, strengthToUse);
  }

  function pickSuggestion(sug: { brand: string; salt: string; strength: string }) {
    setSearchTerm(sug.brand);
    setSelectedSalt(sug.salt);
    setStrength(sug.strength);
    void executePricingLookup(sug.salt, sug.strength);
  }

  // Parse numeric price for display
  function parsePrice(mrpStr?: string): number | null {
    if (!mrpStr) return null;
    const match = mrpStr.match(/(\d+(\.\d+)?)/);
    return match ? parseFloat(match[1]) : null;
  }

  const bestPrice = parsePrice(result?.best?.mrp);

  return (
    <div className="generic-finder-page page-enter">
      <div className="page-heading">
        <div>
          <p className="eyebrow">AFFORDABLE HEALTHCARE DISCOVERY</p>
          <h1>Generic Medicine Finder</h1>
          <p>
            Find government Jan Aushadhi (PMBJP) generic equivalents and compare
            transparent medicine prices. Same active salt, fraction of the cost.
          </p>
        </div>
        <span className="pill-badge">
          <Building2 size={16} /> PMBJP Jan Aushadhi Scheme
        </span>
      </div>

      <div className="generic-finder-grid">
        {/* Left / Top Search Panel */}
        <section className="panel finder-search-panel">
          <form onSubmit={handleSearchSubmit}>
            <div className="section-title">
              <span className="icon-tile mint">
                <Coins size={22} />
              </span>
              <div>
                <h2>Search Branded or Generic Name</h2>
                <p>Lookup by commercial brand (e.g. Dolo, Augmentin) or active salt</p>
              </div>
            </div>

            <div className="search-inputs-row">
              <label className="search-field flex-2">
                <Search size={18} />
                <input
                  type="text"
                  placeholder="Enter medicine or salt name..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  autoFocus
                />
                {searchTerm && (
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => {
                      setSearchTerm("");
                      setSelectedSalt("");
                    }}
                  >
                    <X size={16} />
                  </button>
                )}
              </label>

              <label className="search-field flex-1">
                <input
                  type="text"
                  placeholder="Strength (e.g. 500 mg, 10 mg)"
                  value={strength}
                  onChange={(e) => setStrength(e.target.value)}
                />
              </label>

              <button
                type="submit"
                className="button primary"
                disabled={loading || !searchTerm.trim()}
              >
                {loading ? <LoaderCircle size={18} className="spin" /> : <Search size={18} />}
                <span>Find Generic</span>
              </button>
            </div>

            {selectedSalt && selectedSalt.toLowerCase() !== searchTerm.toLowerCase() && (
              <div className="salt-identified-chip">
                <span>Active Chemical Salt:</span>
                <strong>{selectedSalt}</strong>
              </div>
            )}

            <div className="quick-suggestions-row">
              <span className="suggestions-label">Popular Indian Medicines:</span>
              <div className="suggestion-pills">
                {COMMON_SEARCH_SUGGESTIONS.map((s) => (
                  <button
                    key={s.brand}
                    type="button"
                    className="suggestion-pill"
                    onClick={() => pickSuggestion(s)}
                  >
                    {s.brand} <small>({s.salt})</small>
                  </button>
                ))}
              </div>
            </div>
          </form>
        </section>

        {/* Results Section */}
        <section className="finder-results-section">
          {!hasSearched && (
            <div className="panel empty-finder-card">
              <Coins size={44} className="text-mint" strokeWidth={1.4} />
              <h3>Discover Affordable Generic Options</h3>
              <p>
                The Pradhan Mantri Bhartiya Janaushadhi Pariyojana provides quality
                generic medicines that have the identical active pharmaceutical
                ingredient (API), dosage, and efficacy as branded drugs.
              </p>
              <div className="scheme-benefits">
                <div>
                  <CheckCircle2 size={16} className="text-mint" />
                  <span>50% to 90% savings compared to branded counterparts</span>
                </div>
                <div>
                  <CheckCircle2 size={16} className="text-mint" />
                  <span>Stringent WHO-GMP quality tested batches</span>
                </div>
                <div>
                  <CheckCircle2 size={16} className="text-mint" />
                  <span>Available at 10,000+ Jan Aushadhi Kendras across India</span>
                </div>
              </div>
            </div>
          )}

          {loading && (
            <div className="panel loading-finder-card">
              <LoaderCircle size={36} className="spin text-blue" />
              <h3>Searching Jan Aushadhi & Price Catalogs...</h3>
              <p>Looking up government-capped generic rates for {selectedSalt || searchTerm}...</p>
            </div>
          )}

          {offlineError && !loading && (
            <div className="notice warning finder-warning" role="alert">
              <AlertCircle size={24} />
              <div>
                <h3>PMBJP Pricing Catalog Offline</h3>
                <p>
                  The Jan Aushadhi price database is currently unavailable on the backend.
                  {result?.reason && ` (${result.reason})`}
                </p>
                <p>
                  You can still ask your local pharmacist or Jan Aushadhi Kendra for the
                  generic equivalent of <strong>{selectedSalt || searchTerm}</strong>.
                </p>
              </div>
            </div>
          )}

          {result && !loading && !offlineError && (
            <div className="pricing-report">
              {result.best ? (
                <div className="panel best-generic-card">
                  <div className="best-generic-badge">
                    <Sparkles size={16} /> RECOMMENDED PMBJP GENERIC EQUIVALENT
                  </div>

                  <div className="best-generic-header">
                    <div>
                      <h2>{result.best.brand || result.best.salt}</h2>
                      <p className="generic-salt-line">
                        Active Salt: <strong>{result.best.salt}</strong>
                      </p>
                      <span className="generic-strength-pill">
                        {result.best.strength || strength || "Standard formulation"}
                      </span>
                    </div>

                    <div className="price-tag-box">
                      <span className="price-label">Jan Aushadhi MRP</span>
                      <strong className="price-amount">{result.best.mrp}</strong>
                      <span className="price-unit">per {result.best.unit || "pack"}</span>
                    </div>
                  </div>

                  <div className="savings-highlight-banner">
                    <TrendingDown size={22} className="text-green" />
                    <div>
                      <strong>Significant Savings Opportunity</strong>
                      <p>
                        Branded versions typically retail for ₹25 to ₹75+. Choosing this
                        PMBJP generic equivalent saves an estimated 60% to 85% with identical therapeutic action.
                      </p>
                    </div>
                  </div>

                  <div className="finder-action-row">
                    {onNavigateSafety && (
                      <button
                        type="button"
                        className="button secondary"
                        onClick={() =>
                          onNavigateSafety(
                            medicines.find(
                              (m) =>
                                m.activeIngredient.toLowerCase() ===
                                (result.best?.salt || "").toLowerCase()
                            ) || result.best?.salt || searchTerm
                          )
                        }
                      >
                        <ShieldCheck size={16} />
                        Check Patient Safety
                      </button>
                    )}

                    {onNavigateChat && (
                      <button
                        type="button"
                        className="button secondary"
                        onClick={() =>
                          onNavigateChat(
                            medicines.find(
                              (m) =>
                                m.activeIngredient.toLowerCase() ===
                                (result.best?.salt || "").toLowerCase()
                            ) || result.best?.salt || searchTerm
                          )
                        }
                      >
                        <Stethoscope size={16} />
                        Ask AI Assistant
                      </button>
                    )}

                    {result.best.source && (
                      <span className="source-caption">
                        Source: {result.best.source}
                      </span>
                    )}
                  </div>
                </div>
              ) : (
                <div className="panel no-exact-generic-card">
                  <AlertCircle size={28} className="text-amber" />
                  <div>
                    <h3>No Direct PMBJP Match Found</h3>
                    <p>
                      We did not find an exact listing in the Jan Aushadhi catalog for{" "}
                      <strong>{selectedSalt || searchTerm}</strong>.
                    </p>
                    <p>
                      Check the spelling of the active ingredient, or visit{" "}
                      <a
                        href="http://janaushadhi.gov.in"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="source-link"
                      >
                        janaushadhi.gov.in <ExternalLink size={12} />
                      </a>{" "}
                      for the complete list of 1,800+ government medicines.
                    </p>
                  </div>
                </div>
              )}

              {/* Alternative Generic Strengths & Formulations */}
              {result.alternatives && result.alternatives.length > 0 && (
                <div className="panel alternatives-panel">
                  <div className="section-title">
                    <span className="icon-tile blue">
                      <Pill size={20} />
                    </span>
                    <div>
                      <h3>Alternative Generic Formulations & Strengths</h3>
                      <p>Comparable options available under PMBJP or generic distribution</p>
                    </div>
                  </div>

                  <div className="alternatives-table-wrapper">
                    <table className="alternatives-table">
                      <thead>
                        <tr>
                          <th>Generic Description</th>
                          <th>Strength</th>
                          <th>Unit / Pack</th>
                          <th>Government MRP</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.alternatives.map((alt, idx) => (
                          <tr key={`alt-${idx}`}>
                            <td>
                              <strong>{alt.brand}</strong>
                            </td>
                            <td>
                              <span className="alt-strength-tag">{alt.strength}</span>
                            </td>
                            <td>{alt.unit}</td>
                            <td>
                              <strong className="alt-price">{alt.mrp}</strong>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Informative Guidance */}
              <div className="notice soft-blue finder-info-notice">
                <ShieldCheck size={20} />
                <p>
                  <strong>Clinical Note:</strong> In India, you have the right to request
                  generic medicines at pharmacies. Always ensure your pharmacist confirms
                  the dosage, active salt, and release mechanism match your doctor&apos;s
                  prescription exactly before switching.
                </p>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
