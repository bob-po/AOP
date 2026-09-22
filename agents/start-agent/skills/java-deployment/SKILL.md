---
name: java-deployment
description: Build and run Java Maven/Gradle Spring Boot apps with Docker Compose and optional MySQL/Redis.
---

# Java Deployment Skill

Detection:

- `pom.xml` / `build.gradle` / `build.gradle.kts`
- Multi-module Maven: prefer modules matching `server|web|api|boot`
- Port from `server.port` (default 8080)
- Infra from `application*.yml`: mysql / redis

Defaults:

- Multi-stage Dockerfile: `maven:3.9-eclipse-temurin-<ver>` → `eclipse-temurin:<ver>-jre`
- Build: `mvn -pl <module> -am package -DskipTests`
- Run: `java -jar /app/app.jar`
- When MySQL/Redis required, generate `docker-compose.yml` and wire:
  - `SKY_DATASOURCE_HOST=mysql`
  - `SKY_REDIS_HOST=redis`

Repairs:

- Wrong module / missing jar → adjust `-pl` module
- Port conflict → remap host port
- DB connection refused → wait for mysql healthcheck / fix env hostnames
- Empty Dockerfile → regenerate FROM templates
