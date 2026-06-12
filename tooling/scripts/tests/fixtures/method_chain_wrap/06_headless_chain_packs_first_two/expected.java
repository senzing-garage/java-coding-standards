public class Demo
{
    public void run()
    {
        var summary = findAllActiveSubscribers().filter(predicate)
                                                .sorted()
                                                .distinct()
                                                .toList();
    }
}
