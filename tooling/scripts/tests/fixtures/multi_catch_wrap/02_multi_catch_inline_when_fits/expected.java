public class Demo
{
    public void run()
    {
        try {
            doSomething();
        } catch (IOException | RuntimeException e) {
            handle(e);
        }
    }
}
