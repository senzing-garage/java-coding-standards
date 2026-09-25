public class Demo
{
    public void run()
    {
        assertThrows(SampleException.class, () -> {
            consumerFactory.createConsumer(ConsumerKind.DATABASE, configuration, 250L);
        });
    }
}
