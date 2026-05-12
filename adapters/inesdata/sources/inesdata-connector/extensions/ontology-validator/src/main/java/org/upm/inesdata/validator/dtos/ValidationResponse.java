package org.upm.inesdata.validator.dtos;

import java.util.List;

public class ValidationResponse {

    public boolean conforms;
    public List<Violation> violations;

    public static class Violation {
        public String message;
        public String path;
        public String focusNode;
        public String severity;
    }
}
