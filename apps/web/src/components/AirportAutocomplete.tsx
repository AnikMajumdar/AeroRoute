"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Airport } from "@/lib/api";

interface AirportAutocompleteProps {
  label: string;
  value: Airport | null;
  onChange: (airport: Airport | null) => void;
  placeholder?: string;
}

function formatAirportLabel(airport: Airport): string {
  const code = airport.icao_code || airport.iata_code || airport.ident;
  const location = airport.municipality ? ` (${airport.municipality})` : "";
  return `${code} — ${airport.name}${location}`;
}

function getSearchTerm(text: string): string {
  const separator = text.indexOf(" — ");
  return (separator > 0 ? text.slice(0, separator) : text).trim();
}

export function AirportAutocomplete({
  label,
  value,
  onChange,
  placeholder = "Start typing ICAO, IATA, or airport name...",
}: AirportAutocompleteProps) {
  const [inputText, setInputText] = useState("");
  const [results, setResults] = useState<Airport[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const listId = useRef(`airport-list-${label.replace(/\s+/g, "-").toLowerCase()}`);

  useEffect(() => {
    if (value) {
      setInputText(formatAirportLabel(value));
    }
  }, [value]);

  const searchAirports = useCallback(async (term: string) => {
    const query = getSearchTerm(term);
    if (query.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }

    setLoading(true);
    try {
      const data = await api.searchAirports(query);
      setResults(data);
      setOpen(true);
      setHighlightedIndex(data.length > 0 ? 0 : -1);
    } catch {
      setResults([]);
      setOpen(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (value) return;

    const timer = setTimeout(() => {
      void searchAirports(inputText);
    }, 250);

    return () => clearTimeout(timer);
  }, [inputText, value, searchAirports]);

  function selectAirport(airport: Airport) {
    onChange(airport);
    setInputText(formatAirportLabel(airport));
    setOpen(false);
    setResults([]);
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const next = e.target.value;
    setInputText(next);
    if (value) onChange(null);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightedIndex((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightedIndex((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (e.key === "Enter" && highlightedIndex >= 0) {
      e.preventDefault();
      selectAirport(results[highlightedIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const showEmpty = open && !loading && getSearchTerm(inputText).length >= 2 && results.length === 0;

  return (
    <div ref={wrapperRef} className="relative">
      <label className="block text-sm font-medium text-slate-300 mb-1">{label}</label>
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId.current}
        aria-autocomplete="list"
        value={inputText}
        onChange={handleInputChange}
        onFocus={() => {
          if (!value && getSearchTerm(inputText).length >= 2) {
            void searchAirports(inputText);
          }
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full rounded-lg border border-border bg-card px-4 py-2.5 text-foreground placeholder:text-slate-500 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
      />
      {loading && (
        <span className="absolute right-3 top-9 text-xs text-slate-500">Searching...</span>
      )}
      {open && results.length > 0 && (
        <ul
          id={listId.current}
          role="listbox"
          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-border bg-card shadow-xl"
        >
          {results.map((airport, index) => (
            <li key={airport.id} role="option" aria-selected={index === highlightedIndex}>
              <button
                type="button"
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => selectAirport(airport)}
                className={`w-full px-4 py-2.5 text-left transition-colors ${
                  index === highlightedIndex ? "bg-slate-700/70" : "hover:bg-slate-700/50"
                }`}
              >
                <span className="font-mono text-accent">
                  {airport.icao_code || airport.iata_code || airport.ident}
                </span>
                <span className="ml-2 text-foreground">{airport.name}</span>
                {airport.municipality && (
                  <span className="ml-2 text-sm text-slate-400">{airport.municipality}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {showEmpty && (
        <div className="absolute z-50 mt-1 w-full rounded-lg border border-border bg-card px-4 py-3 text-sm text-slate-400 shadow-xl">
          No matching airports with weather data. Try a medium/large US field (e.g. KJFK, KLAX).
        </div>
      )}
      <p className="mt-1 text-xs text-slate-500">
        Only continental US medium and large airports with ICAO weather reporting are listed.
      </p>
    </div>
  );
}
