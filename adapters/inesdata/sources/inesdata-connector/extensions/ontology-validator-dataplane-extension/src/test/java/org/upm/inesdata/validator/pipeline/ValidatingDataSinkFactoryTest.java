package org.upm.inesdata.validator.pipeline;

import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSink;
import org.eclipse.edc.connector.dataplane.spi.pipeline.DataSinkFactory;
import org.eclipse.edc.connector.dataplane.spi.pipeline.StreamResult;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.result.Result;
import org.eclipse.edc.spi.types.domain.DataAddress;
import org.eclipse.edc.spi.types.domain.transfer.DataFlowStartMessage;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CompletableFuture;

import static org.assertj.core.api.Assertions.assertThat;

class ValidatingDataSinkFactoryTest {

    private final DataSink delegateSink = source -> CompletableFuture.completedFuture(StreamResult.success());

    @Test
    void createSink_bypassesValidationWrapperForKafkaDestinations() {
        var factory = factory(delegateSink);
        var request = requestWithDestination("Kafka");

        var sink = factory.createSink(request);

        assertThat(sink).isSameAs(delegateSink);
    }

    @Test
    void createSink_keepsValidationWrapperForNonKafkaDestinations() {
        var factory = factory(delegateSink);
        var request = requestWithDestination("AmazonS3");

        var sink = factory.createSink(request);

        assertThat(sink).isInstanceOf(ValidatingDataSink.class);
        assertThat(sink).isNotSameAs(delegateSink);
    }

    @Test
    void isKafkaDestination_isCaseInsensitiveAndNullSafe() {
        assertThat(ValidatingDataSinkFactory.isKafkaDestination(requestWithDestination("kafka"))).isTrue();
        assertThat(ValidatingDataSinkFactory.isKafkaDestination(requestWithDestination("AmazonS3"))).isFalse();
        assertThat(ValidatingDataSinkFactory.isKafkaDestination(null)).isFalse();
    }

    private static ValidatingDataSinkFactory factory(DataSink sink) {
        return new ValidatingDataSinkFactory(
                new StubDataSinkFactory(sink),
                () -> null,
                new Monitor() {
                },
                null,
                null,
                "participant",
                java.util.Collections.newSetFromMap(new java.util.concurrent.ConcurrentHashMap<>()),
                null
        );
    }

    private static DataFlowStartMessage requestWithDestination(String type) {
        return DataFlowStartMessage.Builder.newInstance()
                .processId("process-id")
                .sourceDataAddress(DataAddress.Builder.newInstance().type("HttpData").build())
                .destinationDataAddress(DataAddress.Builder.newInstance().type(type).build())
                .build();
    }

    private record StubDataSinkFactory(DataSink sink) implements DataSinkFactory {
        @Override
        public String supportedType() {
            return "test";
        }

        @Override
        public DataSink createSink(DataFlowStartMessage request) {
            return sink;
        }

        @Override
        public Result<Void> validateRequest(DataFlowStartMessage request) {
            return Result.success();
        }
    }
}
