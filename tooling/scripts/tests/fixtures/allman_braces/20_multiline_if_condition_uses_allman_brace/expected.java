public class Demo
{
    public void run(java.util.Set<Integer> missingSet, int fallbackCount)
    {
        for (int x : items) {
            for (int y : nestedItems) {
                if (missingSet.size() > 0
                    && missingSet.size() == fallbackCount)
                {
                    doSomething();
                    return;
                }
            }
        }
    }
}
