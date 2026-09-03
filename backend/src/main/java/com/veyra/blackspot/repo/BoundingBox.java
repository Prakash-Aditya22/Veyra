package com.veyra.blackspot.repo;

public record BoundingBox(double minLon, double minLat, double maxLon, double maxLat) {

    /** Parses "minLon,minLat,maxLon,maxLat", the order Leaflet reports. */
    public static BoundingBox parse(String s) {
        if (s == null || s.isBlank()) {
            throw new IllegalArgumentException("bbox is required");
        }
        String[] p = s.split(",");
        if (p.length != 4) {
            throw new IllegalArgumentException(
                "bbox needs 4 comma-separated numbers (minLon,minLat,maxLon,maxLat), got: " + s);
        }
        double[] v = new double[4];
        for (int i = 0; i < 4; i++) {
            try {
                v[i] = Double.parseDouble(p[i].trim());
            } catch (NumberFormatException e) {
                throw new IllegalArgumentException("bbox value " + (i + 1) + " is not a number: " + p[i]);
            }
        }
        if (v[0] >= v[2] || v[1] >= v[3]) {
            throw new IllegalArgumentException("bbox min must be less than max: " + s);
        }
        return new BoundingBox(v[0], v[1], v[2], v[3]);
    }
}
