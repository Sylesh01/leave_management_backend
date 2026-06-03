package com.demo.filter;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import java.nio.charset.StandardCharsets;
import javax.crypto.SecretKey;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;

import reactor.core.publisher.Mono;

@Component
public class JwtAuthenticationFilter
        implements GlobalFilter, Ordered {

    @Autowired
    private SecretKey secretKey;

    @Override
    public Mono<Void> filter(
            ServerWebExchange exchange,
            GatewayFilterChain chain) {

        String path =
                exchange.getRequest()
                        .getURI()
                        .getPath();

        if (isPublicEndpoint(path)) {
            return chain.filter(exchange);
        }

        String authHeader =
                exchange.getRequest()
                        .getHeaders()
                        .getFirst(HttpHeaders.AUTHORIZATION);

        if (authHeader == null ||
                !authHeader.startsWith("Bearer ")) {

            return unauthorizedResponse(exchange,
                    "Missing Authorization header");
        }

        try {

            String token =
                    authHeader.substring(7);

            Claims claims =
                    Jwts.parser()
                            .verifyWith(secretKey)
                            .build()
                            .parseSignedClaims(token)
                            .getPayload();

            String employeeId =
                    claims.getSubject();

            String role =
                    claims.get("role").toString();

            String username = claims.get("username", String.class);
            if (username == null) {
                username = claims.getSubject();
            }

            ServerHttpRequest request =
                    exchange.getRequest()
                            .mutate()
                            .header("X-Employee-Id",
                                    employeeId)
                            .header("X-Role",
                                    role)
                            .header("X-Username",
                                    username)
                            .header(HttpHeaders.AUTHORIZATION,
                                    authHeader)
                            .build();

            return chain.filter(
                    exchange.mutate()
                            .request(request)
                            .build());

        } catch (Exception ex) {

            return unauthorizedResponse(exchange,
                    "Invalid token");
        }
    }

    private boolean isPublicEndpoint(
            String path) {

        return path.equals("/auth/login")
                || path.equals("/swagger-ui.html")
                || path.startsWith("/swagger-ui/")
                || path.endsWith("/openapi.json")
                || path.startsWith("/v3/api-docs")
                || path.startsWith("/actuator");
    }

    private Mono<Void> unauthorizedResponse(
            ServerWebExchange exchange,
            String message) {
        exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
        exchange.getResponse().getHeaders().setContentType(
                MediaType.APPLICATION_JSON);
        String body = String.format("{\"detail\":\"%s\"}", message);
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        DataBuffer buffer = exchange.getResponse()
                .bufferFactory()
                .wrap(bytes);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    @Override
    public int getOrder() {
        return -1;
    }
}