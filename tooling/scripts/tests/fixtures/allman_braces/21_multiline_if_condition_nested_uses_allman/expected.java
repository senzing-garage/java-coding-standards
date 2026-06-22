public class Demo
{
    public void run(java.util.List<String> items, int maxCount, boolean strict)
    {
        for (String item : items) {
            if (item != null
                && !item.isEmpty() && item.length() < maxCount && strict)
            {
                process(item);
            } else if (item == null
                && !strict && fallbackEnabled && allowDefaults)
            {
                process(defaultItem);
            }
        }
    }
}
