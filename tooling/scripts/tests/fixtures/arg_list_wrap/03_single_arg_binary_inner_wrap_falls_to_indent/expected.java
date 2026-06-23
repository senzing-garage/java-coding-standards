import java.util.Arrays;

public class Demo
{
    public void run(Object[] timers)
    {
        for (Object t : timers) {
            if (t != null) {
                if (t.toString().isEmpty()) {
                    throw new IllegalArgumentException("At least one timer ("
                        + t + ") is duplicated: " + (Arrays.asList(timers)));
                }
            }
        }
    }
}
