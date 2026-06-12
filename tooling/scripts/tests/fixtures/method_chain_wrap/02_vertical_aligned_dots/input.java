public class Demo
{
    public void run()
    {
        String summary = registry.findAllActiveSubscribers().filter(predicate).sorted().distinct().toList();
    }
}
