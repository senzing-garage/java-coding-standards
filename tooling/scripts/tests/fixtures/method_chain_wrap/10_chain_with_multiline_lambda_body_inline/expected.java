public class Demo
{
    public void run(java.util.Map<String, Object>   baseMap,
                    java.util.Map<String, Object>   lookupMap)
    {
        baseMap.keySet().forEach(flag -> {
            if (lookupMap.containsKey(flag)) {
                doSomething(flag);
            }
        });
    }
}
