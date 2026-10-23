/** Default attributes for newly drawn features. */
export const DRAW_DEFAULTS: Record<string, Record<string, any>> = {
  corridor: { width_m: 4, direction: "both", surface: "path", enabled: true },
  emergency_corridor: { width_m: 5, direction: "both", emergency_only: true, enabled: true },
  gate: { role: "both", width_m: 4, enabled: true },
  holding_area: { capacity_persons: null },
  building: { height_m: 8 },
  temple: { height_m: 15 },
  wall: { height_m: 2.5 },
  barricade: { height_m: 1.1 },
};

export const ZONE_LIKE = new Set(["zone", "holding_area", "ghat", "bathing_area", "plaza", "assembly_point", "parking", "transit_hub", "bus_terminal", "queue_lane"]);

export const OWNER_DEPARTMENTS = [
  "Mela Administration",
  "Police Department",
  "Municipal Corporation",
  "Health Department",
  "Irrigation Department",
  "Endowments Department",
  "Fire & Emergency Services",
  "Transport Department",
  "Other",
];

export const ZONE_TYPES = ["ghat", "bathing", "holding", "approach", "corridor", "assembly", "parking", "transit", "medical", "queue", "sector", "other"];
