package org.upm.inesdata.registration_service.config;

import org.springframework.core.convert.converter.Converter;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;

import java.util.Collection;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * A converter that extracts roles from a Keycloak JWT and converts them into a collection of GrantedAuthority.
 * This class implements the Converter interface provided by Spring Security.
 * @author gmv
 */
public class KeycloakRealmRoleConverter implements Converter<Jwt, Collection<GrantedAuthority>> {

    /**
     * Converts the given JWT into a collection of GrantedAuthority based on the roles found in the "realm_access" claim.
     *
     * @param jwt the JWT to convert
     * @return a collection of GrantedAuthority representing the roles from the JWT, or an empty collection if no roles are found
     */
    @Override
    public Collection<GrantedAuthority> convert(Jwt jwt) {
        final Map<String, Object> realmAccess = (Map<String, Object>) jwt.getClaims().get("realm_access");

        if (realmAccess == null || realmAccess.isEmpty()) {
            return Collections.emptyList();
        }

        return ((List<String>) realmAccess.get("roles")).stream()
            .map(SimpleGrantedAuthority::new)
            .collect(Collectors.toList());
    }
}
