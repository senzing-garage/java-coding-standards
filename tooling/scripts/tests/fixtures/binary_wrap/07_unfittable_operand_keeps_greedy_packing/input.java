public class Demo
{
    void check(int retriedCount1, int retriedCount2, Method method)
    {
        while (true) {
            while (true) {
                for (int i = 0; i < 1; i++) {
                    if (method != null) {
                        assertEquals(
                            0,
                            (retriedCount2 - retriedCount1),
                            "Number of retried operations (" + retriedCount1
                            + " vs " + retriedCount2
                            + ") unexpectedly changed for annotated method from "
                            + method.getDeclaringClass().getSimpleName() + ": "
                            + method.toString());
                    }
                }
            }
        }
    }
}
