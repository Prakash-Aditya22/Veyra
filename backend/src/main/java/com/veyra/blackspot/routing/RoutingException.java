package com.veyra.blackspot.routing;

public class RoutingException extends RuntimeException {

    public enum Kind { NO_ROUTE, UNAVAILABLE }

    private final Kind kind;

    public RoutingException(Kind kind, String message) {
        super(message);
        this.kind = kind;
    }

    public RoutingException(Kind kind, String message, Throwable cause) {
        super(message, cause);
        this.kind = kind;
    }

    public Kind kind() {
        return kind;
    }
}
