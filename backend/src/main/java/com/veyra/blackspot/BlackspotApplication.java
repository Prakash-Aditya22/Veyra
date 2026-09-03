package com.veyra.blackspot;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

/**
 * DataSource auto-configuration is excluded at the class level and enabled
 * only when DATABASE_URL is present, so the app boots for health checks and
 * unit tests without a database.
 */
@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
public class BlackspotApplication {
    public static void main(String[] args) {
        SpringApplication.run(BlackspotApplication.class, args);
    }
}
