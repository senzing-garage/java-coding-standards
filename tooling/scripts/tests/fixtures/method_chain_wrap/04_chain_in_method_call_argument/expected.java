public class Demo
{
    public void run()
    {
        consumer.accept(registry.fetch().normalize().validate().toResult());
    }
}
