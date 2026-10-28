public class Demo
{
    void conflicts(Options options, URI sqsUri)
    {
        IllegalStateException exception = assertThrows(
            IllegalStateException.class,
            () -> {
                options.setSQSInfoUri(sqsUri);
            },
            "Should throw IllegalStateException when SQS conflicts with RabbitMQ URI");
    }
}
